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
	<p><a href="/">Home</a> --&gt; <a href="/administrator/">Administrator Panel</a> --&gt; <a href="/fee_balances.html">Enter Fee Balances</a> --&gt; <a href="/cgi-bin/update_fee_balances.cgi">Update Fee Balances</a>
	<hr> 
};

unless ($authd) {

	if ($logd_in) {
		$content .=
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj :: Exam Management Information System :: Enter Fee Balances</title>
</head>
<body>
$header
<p><span style="color: red">Sorry, you do not have the appropriate privileges to update fee balances.</span> Only the administrator is authorized to take this action.
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
		print "Location: /login.html?cont=/cgi-bin/update_fee_balances.cgi\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";
       		my $res = 
qq!
<html lang="en">
<head>
<title>Spanj::Exam Management Information System</title>
</head>
<body>
You should have been redirected to <a href="/login.html?cont=/cgi-bin/update_fee_balances.cgi">/login.html?cont=/cgi-bin/update_fee_balances.cgi</a>. If you were not, <a href="login.html?cont=/cgi-bin/update_fee_balances.cgi">Click Here</a> 
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

if ( exists $ENV{"QUERY_STRING"} ) {

	if ( $ENV{"QUERY_STRING"} =~ /\&?redir=1\&?/i ) {
		$feedback = qq*<P><SPAN style="color: green">Your changes have been saved!</SPAN>*;
	}
}

$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

PM: {

	if ($post_mode) {
	
		my $prep_stmt4 = $con->prepare("REPLACE INTO `fee_arrears` VALUES(?,?,?)");
		
		unless ($prep_stmt4) {
			print STDERR "Couldn't prepare REPLACE INTO `fee_arrears`: ", $prep_stmt4->errstr, $/;
		}

		my @invalid_adms = ();

		for my $auth_param ( keys %auth_params) {

			if ( $auth_param =~ /adm_(\d+)/ ) {

				my $adm = $1;
				#had forgotten to allow -ve arrears(prepayments)
				if ( exists $auth_params{"${adm}_arrears"} and  $auth_params{"${adm}_arrears"} =~ /^\-?\d{1,10}(\.\d{1,2})?$/ ) {

					if ( exists $auth_params{"${adm}_next_term_fees"} and  $auth_params{"${adm}_next_term_fees"} =~ /^\d{1,10}(\.\d{1,2})?$/ ) {
						my $rc = $prep_stmt4->execute($adm, $auth_params{"${adm}_arrears"}, $auth_params{"${adm}_next_term_fees"});
						unless ($rc) {
							print STDERR "Couldn't prepare REPLACE INTO `fee_arrears`: ", $prep_stmt4->errstr, $/;
						}
					}
					else {
						push @invalid_adms,$adm;
					}
				}
				else {
					push @invalid_adms,$adm;
				}
			}
		}

		$feedback = qq*<P><SPAN style="color: green">Your changes have been saved!</SPAN>*;

		if ( scalar(@invalid_adms) > 0 ) {
			my $invalids = join(", ", @invalid_adms);
			$feedback = qq*<P><SPAN style="color: red">Invalid arrears and/or next term's fees provided for the following adm numbers: </SPAN>$invalids*;
		}

		$con->commit();

		#log action
		my @today = localtime;	
		my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];
					
		open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");

       		if ($log_f) {	
       			@today = localtime;	
			my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
			flock ($log_f, LOCK_EX) or print STDERR "Could not log update fee balances due to flock error: $!$/";
			seek ($log_f, 0, SEEK_END);
				 
			print $log_f "1 UPDATE FEE BALANCES $time\n";
			flock ($log_f, LOCK_UN);
       			close $log_f;
       		}
		else {
			print STDERR "Could not log update fee balances for 1: $!\n";
		}

		$post_mode = 0;
		last PM;
	}

}

if ( not $post_mode ) {

	my $current_yr = (localtime)[5] + 1900; 

	my %table_class_lookup = ();
	#my %class_table_lookup = ();
 
	my $prep_stmt1 = $con->prepare("SELECT table_name,class,start_year FROM student_rolls WHERE grad_year >= ?");

	if ($prep_stmt1) {

		my $rc = $prep_stmt1->execute($current_yr);

		if ($rc) {

			while ( my @rslts = $prep_stmt1->fetchrow_array() ) {

				my $class = uc($rslts[1]);
				my $class_yr = ($current_yr - $rslts[2]) + 1;
				
				$class =~ s/\d+/$class_yr/;

				#$class_table_lookup{$class} = $rslts[0];
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

	my %studs;

	if ( scalar(keys %table_class_lookup) > 0 ) {

		for my $roll (keys %table_class_lookup) {

			my $class = $table_class_lookup{$roll};
 
			my $prep_stmt2 = $con->prepare("SELECT adm,s_name,o_names FROM `$roll`");
			if ($prep_stmt2) {

				my $rc = $prep_stmt2->execute();

				if ( $rc ) {

					while ( my @rslts = $prep_stmt2->fetchrow_array() ) {
						$studs{$rslts[0]} = {"name" => "$rslts[2] $rslts[1]", "class" => $class};
					}

				}

				else {
					print STDERR "Couldn't prepare SELECT FROM $roll: ", $prep_stmt2->errstr, $/;
				}

			}
			else {
				print STDERR "Couldn't prepare SELECT FROM $roll: ", $prep_stmt2->errstr, $/;
			}

		}

		my $prep_stmt3 = $con->prepare("SELECT adm,arrears,next_term_fees FROM `fee_arrears`");

		if ( $prep_stmt3 ) {

			my $rc = $prep_stmt3->execute();

			if ($rc) {
				while ( my @rslts = $prep_stmt3->fetchrow_array() ) {

					if ( exists $studs{$rslts[0]} ) {
						$studs{$rslts[0]}->{"arrears"} = $rslts[1];
						$studs{$rslts[0]}->{"next_term_fees"} = $rslts[2];
					}

				}
			}
			else {
				print STDERR "Couldn't execute SELECT FROM fee_arrears: ", $prep_stmt3->errstr, $/;
			}

		}
		else {
			print STDERR "Couldn't prepare SELECT FROM fee_arrears: ", $prep_stmt3->errstr, $/;
		}		
	}

	$content = 
qq*
<!DOCTYPE html>
<HTML lang="en">
<META http-equiv="Content-Type" content="text/html; charset=ISO-8859-1">
<HEAD>
<SCRIPT type="text/javascript">

var num_re = /^[\-\+]?([0-9]{0,10})(\\.([0-9]{0,2}))?\$/;

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

</SCRIPT>

<TITLE>Spanj :: Exam Management Information System :: Update Fee Balances</TITLE>
</HEAD>
<BODY>
$header
<p><a href="/cgi-bin/upload_fee_balances.cgi?step=1">Use Uploaded Data</a>
$feedback
<FORM method="POST" action="/cgi-bin/update_fee_balances.cgi">
*;
 
	my $current_class = "";

	#compare classes then adm nos
	for my $stud (sort { my $cmp_0 = $studs{$a}->{"class"} cmp $studs{$b}->{"class"}; return $cmp_0 unless ($cmp_0 == 0); return $a <=> $b  } keys %studs) {
		#breaking between classes 
		if ( $studs{$stud}->{"class"} ne $current_class ) {
			#close the table, write header, open a new table.
			unless ($current_class eq "") {
				$content .= "</TBODY></TABLE>";
			}
			$current_class = $studs{$stud}->{"class"};
			$content .= "<H1>$current_class</H1>";

			$content .= qq!<TABLE border="1" cellpadding="5%" cellspacing="5%"><THEAD><TH>Adm No.</TH><TH>Name</TH><TH>Arrears</TH><TH>Next Term's Fees</TH></THEAD><TBODY>!;
		}

		$content .= qq!<TR><TD><INPUT type="hidden" name="adm_$stud" value="$stud">$stud</TD><TD>$studs{$stud}->{"name"}</TD><TD><SPAN style="color: red" id="${stud}_arrears_err"></SPAN><INPUT type="text" size="15" name="${stud}_arrears" id="${stud}_arrears" value="$studs{$stud}->{'arrears'}" onkeyup="check_amount('${stud}_arrears')"></TD><TD><SPAN style="color: red" id="${stud}_next_term_fees_err"></SPAN><INPUT style="color: gray" type="text" size="15" name="${stud}_next_term_fees" id="${stud}_next_term_fees" value="$studs{$stud}->{'next_term_fees'}" onkeyup="check_amount('${stud}_next_term_fees')"></TD>!;

	}

	$content .=
qq*
</TBODY></TABLE>
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

