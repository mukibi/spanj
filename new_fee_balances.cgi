#!/usr/bin/perl

use strict;
use warnings;

use DBI;
use Fcntl qw/:flock SEEK_END/;
use Storable qw/freeze thaw/;

require "./conf.pl";

our($db,$db_user,$db_pwd,$log_d,$doc_root,$upload_dir,$modem_manager1);

my %session;
my %auth_params;

my $logd_in = 0;
my $authd = 0;

my $con;

if ( exists $ENV{"HTTP_SESSION"} ) {

	my @session_data = split/&/,$ENV{"HTTP_SESSION"};
	my @tuple;

	for my $unprocd_tuple (@session_data) {
		#came to learn (as often happens, purely by accident)
		#doing a split/=/,x= will give a list with a size of 1
		#desirable here (where it's OK to ignore unset vars)
		#would be awful where even a blank var means something (e.g
		#logging in with a blank password)
		@tuple = split/\=/,$unprocd_tuple;

		if (@tuple == 2) {
			$tuple[0] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$tuple[1] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$session{$tuple[0]} = $tuple[1];		
		}
	}

	#logged in 
	if (exists $session{"id"}) {
		$logd_in++;
		my $id = $session{"id"};
		if ($id eq "1" or $id eq "2") {
			$authd++;
		}
	}
}

my $content = '';
my $feedback = '';
my $js = '';
my $header =
qq{
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a> --&gt;  <a href="/administrator/">Administrator Panel</a>--&gt; <a href="/fee_balances.html">Enter Fee Balances</a> --&gt; <a href="/cgi-bin/new_fee_balances.cgi">New Fee Balances</a>
	<hr> 
};

unless ($authd) {

	if ($logd_in) {
		$content .=
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj :: Exam Management Information System</title>
</head>
<body>
$header
<p><span style="color: red">Sorry, you do not have the appropriate privileges to create new fee balances.</span> Only the administrator is authorized to take this action.
</body>
</html> 
*;

		print "Status: 200 OK\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";

		my $len = length($content);
		print "Content-Length: $len\r\n";

		my @new_sess_array = ();

		for my $sess_key (keys %session) {
			push @new_sess_array, $sess_key."=".$session{$sess_key};        
		}
		my $new_sess = join ('&',@new_sess_array);

		print "X-Update-Session: $new_sess\r\n";

		print "\r\n";
		print $content;
		exit 0;
	}

	else {
		print "Status: 302 Moved Temporarily\r\n";
		print "Location: /login.html?cont=/cgi-bin/new_fee_balances.cgi\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";
       		my $res = 
qq!
<html lang="en">
<head>
<title>Spanj::Exam Management Information System</title>
</head>
<body>
You should have been redirected to <a href="/login.html?cont=/cgi-bin/new_fee_balances.cgi">/login.html?cont=/cgi-bin/new_fee_balances.cgi</a>. If you were not, <a href="login.html?cont=/cgi-bin/new_fee_balances.cgi">Click Here</a> 
</body>
</html>!;

		my $content_len = length($res);	
		print "Content-Length: $content_len\r\n";
		print "\r\n";
		print $res;
		exit 0;
	}
}

my $post_mode = 0;
my $boundary = undef;
my $multi_part = 0;

if (exists $ENV{"REQUEST_METHOD"} and uc($ENV{"REQUEST_METHOD"}) eq "POST") {
	
	if (exists $ENV{"CONTENT_TYPE"}) {
		if ($ENV{"CONTENT_TYPE"} =~ m!multipart/form-data;\sboundary=(.+)!i) {
			$boundary = $1;
			$multi_part++;
		}
	}

	unless ($multi_part) {
		my $str = "";

		while (<STDIN>) {
        	       	$str .= $_;
	       	}

		my $space = " ";
		$str =~ s/\x2B/$space/ge;
		my @auth_req = split/&/,$str;

		for my $auth_req_line (@auth_req) {

			my $eqs = index($auth_req_line, "=");	
			if ($eqs > 0) {
				my ($k, $v) = (substr($auth_req_line, 0, $eqs), substr($auth_req_line, $eqs + 1)); 

				
				$k =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
				$v =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
				$auth_params{$k} = $v;
			}
		}
	}
	#processing data sent 
	$post_mode++;
}

$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

PM: {
	if ($post_mode) {

		my $baseline_next_term_fees = 0;
		if ( exists $auth_params{"next_term_fees"} and length($auth_params{"next_term_fees"}) > 0 ) {
			if ( $auth_params{"next_term_fees"} =~ /^\d{1,10}(\.\d{1,2})?$/ ) {
				$baseline_next_term_fees = $auth_params{"next_term_fees"};
			}
			else {
				$feedback = qq!<p><span style="color: red">Invalid amount specified</span>!;
				$post_mode = 0;
				last PM;
			}
		}

		my %exceptions = ();
		my $all_amounts_valid = 1;

		#read exceptions
		for my $auth_param (keys %auth_params) {

			if ($auth_param =~ /^next_term_fees_exception_(\d+)_/) {

				my $exception_id = $1; 
				if ( exists $auth_params{"amount_next_term_fees_exception_$exception_id"} and $auth_params{"amount_next_term_fees_exception_$exception_id"} =~ /^\d{1,10}(\.\d{1,2})?$/ ) {
					my $roll = $auth_params{$auth_param};
					$exceptions{$roll} = $auth_params{"amount_next_term_fees_exception_$exception_id"};
				}
				else {
					$all_amounts_valid = 0;
					last;
				}

			}

		}

		unless ($all_amounts_valid) {
			$feedback = qq!<p><span style="color: red">Invalid amount specified</span>!;
			$post_mode = 0;
			last PM;		
		}

		#truncate table
		$con->do("TRUNCATE TABLE `fee_arrears`");

		my $current_yr = (localtime)[5] + 1900; 

		#read current students
		my %current_rolls = ();
		my $prep_stmt2 = $con->prepare("SELECT table_name FROM student_rolls WHERE grad_year >= ?");

		if ($prep_stmt2) {

			my $rc = $prep_stmt2->execute($current_yr);
			if ($rc) {	
				while ( my @rslts = $prep_stmt2->fetchrow_array() ) {
					$current_rolls{$rslts[0]}++;
				}
			}
			else {
				print STDERR "Couldn't execute SELECT FROM student_rolls: ", $prep_stmt2->errstr, $/;
			}

		}
		else {
			print STDERR "Couldn't prepare SELECT FROM student_rolls: ", $prep_stmt2->errstr, $/;
		}

		if ( scalar(keys %current_rolls) > 0 ) {

			my %studs = ();

			my @where_clause_bts = ();
			foreach (keys %current_rolls) {
				push @where_clause_bts, "table_name=?";
			}

			my $where_clause = join (" OR ", @where_clause_bts); 

			my $prep_stmt3 = $con->prepare("SELECT adm_no,table_name FROM adms WHERE $where_clause");

			if ( $prep_stmt3 ) {

				my $rc = $prep_stmt3->execute(keys %current_rolls);

				if ($rc) {
					while ( my @rslts = $prep_stmt3->fetchrow_array() ) {
						$studs{$rslts[0]} = $rslts[1];
					}
				}
				else {
					print STDERR "Couldn't execute SELECT FROM adms: ", $prep_stmt3->errstr, $/;
				}

			}
			else {
				print STDERR "Couldn't prepare SELECT FROM adms: ", $prep_stmt3->errstr, $/;		
			}

			my $prep_stmt4 = $con->prepare("INSERT INTO `fee_arrears` VALUES(?,0,?)");

			if ($prep_stmt4) {

				for my $stud (keys %studs) {

					my $next_term_fees = $baseline_next_term_fees;

					if ( exists $exceptions{$studs{$stud}} ) {
						$next_term_fees = $exceptions{$studs{$stud}};
					}

					my $rc = $prep_stmt4->execute($stud, $next_term_fees);
					unless ($rc) {
						print STDERR "Couldn't execute INSERT INTO `fee_arrears`: ", $prep_stmt4->errstr, $/;
					}
				}
			}

			else {
				print STDERR "Couldn't prepare INSERT INTO `fee_arrears`: ", $prep_stmt4->errstr, $/;		
			}

			#log action
			my @today = localtime;	
			my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];
					
			open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");

      	 		if ($log_f) {	
       				@today = localtime;	
				my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
				flock ($log_f, LOCK_EX) or print STDERR "Could not log create new fee balances due to flock error: $!$/";
				seek ($log_f, 0, SEEK_END);
				 
				print $log_f "1 CREATE NEW FEE BALANCES $time\n";
				flock ($log_f, LOCK_UN);
       				close $log_f;
       			}
			else {
				print STDERR "Could not log create new fee balances for 1: $!\n";
			}
		}

		print "Status: 302 Moved Temporarily\r\n";
		print "Location: /cgi-bin/update_fee_balances.cgi\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";
       		my $res = 
qq!
<html lang="en">
<head>
<title>Spanj :: Exam Management Information System :: Enter Fee Balances</title>
</head>
<body>
You should have been redirected to <a href="/cgi-bin/update_fee_balances.cgi">/cgi-bin/update_fee_balances.cgi</a>. If you were not, <a href="/cgi-bin/update_fee_balances.cgi">Click Here</a> 
</body>
</html>!;
		my $content_len = length($res);	
		print "Content-Length: $content_len\r\n";
		print "\r\n";
		print $res;

		$con->commit();
		$con->disconnect();

		exit 0;
	}
}

if ( not $post_mode ) {

	my $current_yr = (localtime)[5] + 1900; 
	my %grouped_classes = ("1"=> "1", "2"=> "2", "3"=> "3","4"=> "4");
	
	my $prep_stmt = $con->prepare("SELECT value FROM vars WHERE id='1-classes' LIMIT 1");

	if ($prep_stmt) {
		my $rc = $prep_stmt->execute();
		if ($rc) {
			while (my @rslts = $prep_stmt->fetchrow_array()) {
				my @classes = split/,/, $rslts[0];
				%grouped_classes = ();
				for my $class (@classes) {
					if ($class =~ /(\d+)/) {	
						$grouped_classes{$1}->{$class}++;
					}
				}
			}
		}
		else {
			print STDERR "Couldn't execute SELECT FROM vars: ", $prep_stmt->errstr, $/;
		}
	}
	else {
		print STDERR "Couldn't prepare SELECT FROM vars: ", $prep_stmt->errstr, $/;		
	}

	my %class_table_lookup = ();
	my %table_class_lookup = ();

	my $prep_stmt1 = $con->prepare("SELECT table_name,class,start_year FROM student_rolls WHERE grad_year >= ?");

	if ($prep_stmt1) {

		my $rc = $prep_stmt1->execute($current_yr);
		if ($rc) {	
			while ( my @rslts = $prep_stmt1->fetchrow_array() ) {

				my $class = $rslts[1];
				my $class_yr = ($current_yr - $rslts[2]) + 1;
				
				$class =~ s/\d+/$class_yr/;

				$class_table_lookup{$class} = $rslts[0];
				$table_class_lookup{$rslts[0]} = $class;

			}
		}
		else {
			print STDERR "Couldn't execute SELECT FROM student_rolls: ", $prep_stmt1->errstr, $/;
		}
	}
	else {
		print STDERR "Couldn't prepare SELECT FROM student_rolls: ", $prep_stmt1->errstr, $/;
	}


	my @class_yr_js_hashes = ();	

	for my $class_yr (sort {$a <=> $b} keys %grouped_classes) {

		my @class_yr_members = ();	

		my @classes = keys %{$grouped_classes{$class_yr}};
		
		for my $class (sort {$a cmp $b} @classes) {
			if ( exists $class_table_lookup{$class} ) {	
				push @class_yr_members, "{class: '$class', roll: '$class_table_lookup{$class}'}";
			}
		}

		my $class_yr_members_str = join(", ", @class_yr_members);
 
		push @class_yr_js_hashes, "{year: $class_yr, members: [$class_yr_members_str]}";
		
	}

	my $classes_js = join(", ", @class_yr_js_hashes);
	

	$content =
qq*
<!DOCTYPE html>
<HTML lang="en">
<META http-equiv="Content-Type" content="text/html; charset=ISO-8859-1">
<HEAD>
<TITLE>Spanj :: Exam Management Information System :: Create New Fee Balances</TITLE>

<SCRIPT type="text/javascript">

var num_re = /^([0-9]{0,10})(\\.([0-9]{0,2}))?\$/;
var classes = [$classes_js];
var exception_cntr = 0;

function check_amount(elem) {

	var amnt = document.getElementById(elem).value;
	var match_groups = amnt.match(num_re);

	if ( match_groups ) {
		document.getElementById(elem + "_err").innerHTML = "";
	}
	else {
		document.getElementById(elem + "_err").innerHTML = "\*";
	}
}

function add_exception() {

	var classes_select = '<TABLE cellspacing="5%" cellpadding="5%"><TR>';

	for ( var i = 0; i < classes.length; i++) {

		classes_select += '<TD>';

		var classes_in_yr = classes[i].members;		
		for ( var j = 0; j < classes_in_yr.length; j++ ) {

			classes_select += '<LABEL for="next_term_fees_exception_' + classes_in_yr[j].class  + '_' + exception_cntr + '"></LABEL>' + classes_in_yr[j].class + '<INPUT type="checkbox" name="next_term_fees_exception_' + exception_cntr + '_' + classes_in_yr[j].class + '" value="' + classes_in_yr[j].roll + '"><BR>';

		}
	}
	classes_select +='</TABLE>';

	var new_exception_html = '<HR>' + classes_select + '<TABLE><TR><TH><LABEL for="amount_next_term_fees_exception_' + exception_cntr + '" >Next Term\\'s Fees<LABEL></TH><TD><span style="color: red" id="amount_next_term_fees_exception_' + exception_cntr + '_err"></span><INPUT type="text" size="15" id="amount_next_term_fees_exception_' + exception_cntr + '" name="amount_next_term_fees_exception_' + exception_cntr + '" onkeyup="check_amount(\\'amount_next_term_fees_exception_' + exception_cntr + '\\')" onmouseover="check_amount(\\'amount_next_term_fees_exception_' + exception_cntr + '\\')"></TD></TABLE>';

	var new_exception = document.createElement("div");
	new_exception.innerHTML = new_exception_html;

	document.getElementById("exceptions").appendChild(new_exception);

	exception_cntr++;

}

</SCRIPT>

</HEAD>
<BODY>
$header
$feedback
<FORM method="POST" action="/cgi-bin/new_fee_balances.cgi">
<TABLE cellspacing="5%" cellpadding="5%">
<TR><TH><LABEL>Next Term's Fees</LABEL></TH><TD><SPAN style="color: red" id="next_term_fees_err"></SPAN><INPUT type="text" size="15" id="next_term_fees" name="next_term_fees" onkeyup="check_amount('next_term_fees')" onmouseover="check_amount('next_term_fees')"></TD>
<TR><TD colspan="2" style="text-align: right"><input type="button" value="Add Exception" onclick="add_exception()">
</TABLE>

<DIV id="exceptions">

</DIV>
<p><em>NOTE: Clicking 'Save' will reset all arrears to 0.</em>
<p><INPUT type="submit" name="save" value="Save">
</FORM>

</BODY>
</HTML>
*;

}

print "Status: 200 OK\r\n";
print "Content-Type: text/html; charset=UTF-8\r\n";

my $len = length($content);
print "Content-Length: $len\r\n";

my @new_sess_array = ();
for my $sess_key (keys %session) {
	push @new_sess_array, $sess_key."=".$session{$sess_key};        
}
my $new_sess = join ('&',@new_sess_array);

print "X-Update-Session: $new_sess\r\n";

print "\r\n";
print $content;
if ($con) {
	$con->disconnect();
}
