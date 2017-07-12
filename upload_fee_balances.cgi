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
		if ($id eq "1") {
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
	<p><a href="/">Home</a> --&gt; <a href="/fee_balances.html">Enter Fee Balances</a> --&gt; <a href="/cgi-bin/upload_fee_balances.cgi">Upload Fee Balances</a>
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
<p><span style="color: red">Sorry, you do not have the appropriate privileges to upload fee balances.</span> Only the administrator is authorized to take this action.
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
		print "Location: /login.html?cont=/cgi-bin/upload_fee_balances.cgi\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";
       		my $res = 
qq!
<html lang="en">
<head>
<title>Spanj::Exam Management Information System</title>
</head>
<body>
You should have been redirected to <a href="/login.html?cont=/cgi-bin/upload_fee_balances.cgi">/login.html?cont=/cgi-bin/upload_fee_balances.cgi</a>. If you were not, <a href="login.html?cont=/cgi-bin/upload_fee_balances.cgi">Click Here</a> 
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

my $step = 1;
if ( exists $ENV{"QUERY_STRING"} ) {

	if ( $ENV{"QUERY_STRING"} =~ /\&?step=([0-9]+)\&?/i ) {
		$step = $1;
	}

}

$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

PM: {
	if ($post_mode) {

		if ($step == 3) {

			my %seen_cols =();
			my $column_collision=0;

			my ($dataset_id,$foreign_key,$arrears,$next_term_fees) = (undef,undef,undef,undef);

			if ( exists $auth_params{"dataset_id"} and $auth_params{"dataset_id"} =~ /^\d+$/ ) {
				$dataset_id = $auth_params{"dataset_id"};
			}

			if ( exists $auth_params{"foreign_key"} and $auth_params{"foreign_key"} =~ /^\d+$/ ) {
				$foreign_key = $auth_params{"foreign_key"};
				$seen_cols{$foreign_key}++;
			}
			else {
				$feedback = qq!<P><SPAN style="color: red">Invalid column selected</SPAN>!;
				$post_mode = 0;
				last PM;
			}

			if ( exists $auth_params{"arrears"} and $auth_params{"arrears"} =~ /^\d+$/ ) {
				$arrears = $auth_params{"arrears"};
				if (exists $seen_cols{$arrears}) {
					$column_collision++;
				}
				$seen_cols{$arrears}++;
			}
			else {
				$feedback = qq!<P><SPAN style="color: red">Invalid column selected</SPAN>!;
				$post_mode = 0;
				last PM;
			}

			if ( exists $auth_params{"next_term_fees"} and $auth_params{"next_term_fees"} =~ /^\d+$/ ) {
				$next_term_fees = $auth_params{"next_term_fees"};
				if (exists $seen_cols{$next_term_fees}) {
					$column_collision++;
				}
				$seen_cols{$next_term_fees}++;
			}
			else {
				$feedback = qq!<P><SPAN style="color: red">Invalid column selected</SPAN>!;
				$post_mode = 0;
				last PM;
			}

			if (not defined $dataset_id or not defined $foreign_key or not defined $arrears or not defined $next_term_fees) {
				$feedback = qq!<P><SPAN style="color: red">Invalid request.</SPAN>!;
				$post_mode = 0;
				last PM;
			}

			if ($column_collision) {
				$feedback = qq!<P><SPAN style="color: red">One column was selected more than once.</SPAN>!;
				$post_mode = 0;
				last PM;
			}

			my %data;

			open (my $f, "<$upload_dir/$dataset_id");
			my $lines = 0;

			while ( <$f> ) {

				chomp;
				$lines++;

				my $line = $_;

				my @cols = split/,/,$line;

				KK: for (my $i = 0; $i < (scalar(@cols) - 1); $i++) {
					#escaped
					if ( $cols[$i] =~ /(.*)\\$/ ) {

						my $non_escpd = $1;
						$cols[$i] = $non_escpd . "," . $cols[$i+1];

						splice(@cols, $i+1, 1);
						redo KK;
					}

					#assume that quotes will be employed around
					#an entire field
					#has it been opened?
					if ($cols[$i] =~ /^".+/) {
						#has it been closed? 
						unless ( $cols[$i] =~ /.+"$/ ) {
							#assume that the next column 
							#is a continuation of this one.
							#& that a comma was unduly pruned
							#between them
							$cols[$i] = $cols[$i] . "," . $cols[$i+1];
							splice (@cols, $i+1, 1);
							redo KK;
						}
					}
				}

				for (my $j = 0; $j < @cols; $j++) {
					if ($cols[$j] =~ /^"(.*)"$/) {
						$cols[$j] = $1; 
					}
				}

				if ( $lines > 1 ) {

					if ( $cols[$foreign_key] =~ /^\d+$/ ) {

						my $arrears_amnt = 0;
						my $next_term_fees_amnt = undef;

						if ( $cols[$arrears] =~ /^\-?\d{1,10}(\.\d{1,2})?$/ ) {
							$arrears_amnt = $cols[$arrears];
						}

						if ( $cols[$next_term_fees] =~ /^\d{1,10}(\.\d{1,2})?$/ ) {
							$next_term_fees_amnt = $cols[$next_term_fees];
						}
						
						$data{$cols[$foreign_key]} = { "arrears" => $arrears_amnt, "next_term_fees" => $next_term_fees_amnt };
					}
					
				}
			}

			#without next term fees
			my $prep_stmt7 = $con->prepare("UPDATE fee_arrears SET arrears=? WHERE adm=? LIMIT 1");
			#with next term fees
			my $prep_stmt8 = $con->prepare("UPDATE fee_arrears SET arrears=?,next_term_fees=? WHERE adm=? LIMIT 1");

			for my $stud (keys %data) {
				#with next term fees
				if ( defined $data{$stud}->{"next_term_fees"} ) {
					my $rc = $prep_stmt8->execute($data{$stud}->{"arrears"}, $data{$stud}->{"next_term_fees"}, $stud);
					unless ($rc) {
						print STDERR "Could not execute UPDATE fee_arrears: ", $con->errstr, $/;
					}
				}
				#without next term fees
				else {
					my $rc = $prep_stmt7->execute($data{$stud}->{"arrears"}, $stud);
					unless ($rc) {
						print STDERR "Could not execute UPDATE fee_arrears: ", $con->errstr, $/;
					}
				}
			}

			$con->commit();

			#log
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

			#redirect to update fee balances with suitable message
			print "Status: 302 Moved Temporarily\r\n";
			print "Location: /cgi-bin/update_fee_balances.cgi?redir=1\r\n";
			print "Content-Type: text/html; charset=UTF-8\r\n";
       			my $res = 
qq!
<html lang="en">
<head>
<title>Spanj :: Exam Management Information System :: Enter Fee Balances</title>
</head>
<body>
You should have been redirected to <a href="/cgi-bin/update_fee_balances.cgi?redir=1">/cgi-bin/update_fee_balances.cgi?redir=1</a>. If you were not, <a href="/cgi-bin/update_fee_balances.cgi?redir=1">Click Here</a> 
</body>
</html>!;
			my $content_len = length($res);	
			print "Content-Length: $content_len\r\n";
			print "\r\n";
			print $res;

		}

		if ($step == 2) {

	
		my $dataset_id = undef;
		if ( exists $auth_params{"dataset"} and $auth_params{"dataset"} =~ /^\d+$/ ) {
			$dataset_id = $auth_params{"dataset"};
		}

		if (not defined $dataset_id) {
			$feedback = qq!<SPAN style="color: red">Invalid dataset specified.</SPAN>!;
			$post_mode = 0;
			last PM;
		}

		my ($foreign_key,$dataset_header) = (undef,undef);

		my $prep_stmt6 = $con->prepare("SELECT id,foreign_key,header FROM datasets WHERE id=?");
	
		if ($prep_stmt6) {
			my $rc = $prep_stmt6->execute($dataset_id);
			if ($rc) {
				while ( my @rslts = $prep_stmt6->fetchrow_array() ) {
					$foreign_key = $rslts[1];
					$dataset_header = $rslts[2];
				}
			}
			else {
				print STDERR "Could not execute SELECT FROM datasets: ", $con->errstr, $/;
			}
		}
		else {
			print STDERR "Could not prepare SELECT FROM datasets: ", $con->errstr, $/;
		}

		if (not defined $foreign_key) {
			$feedback = qq!<SPAN style="color: red">The dataset requested does not exist.</SPAN>!;
			$post_mode = 0;
			last PM;
		}

		$content =
qq*
<!DOCTYPE html>
<HTML lang="en">
<META http-equiv="Content-Type" content="text/html; charset=ISO-8859-1">
<HEAD>
<TITLE>Spanj :: Exam Management Information System :: Upload Fee Balances</TITLE>
</HEAD>
<BODY>
$header
$feedback
*;
		my @header_bts = split/\$#\$#\$/,$dataset_header;
			
		my $header_opts = "";

		for (my $i = 0; $i < @header_bts; $i++) {

			#don't allow primary key
			next if ($i == $foreign_key);
			$header_opts .= qq!<OPTION value="$i" title="$header_bts[$i]">$header_bts[$i]</OPTION>!;

		}

		$content .=
qq!
<FORM method="POST" action="/cgi-bin/upload_fee_balances.cgi?step=3">
<INPUT type="hidden" name="foreign_key" value="$foreign_key">
<INPUT type="hidden" name="dataset_id" value="$dataset_id">
<P>Which column corresponds to each of the following:
<TABLE>
<TR><TD><LABEL for="arrears">Arrears</LABEL><TD><SELECT name="arrears">$header_opts</SELECT>
<TR><TD><LABEL for="next_term_fees">Next Term Fees</LABEL><TD><SELECT name="next_term_fees">$header_opts</SELECT>
<TR><TD><INPUT type="submit" name="continue" value="Continue">
</TABLE>
</FORM>
</BODY>
</HTML>
!;
	
		}
	}
}

if (not $post_mode) {
	#which dataset?
	#which column corresponds to [arrears,next term's fees]?
	

	#if ($step == 1) {

		my %datasets = ();

		my $prep_stmt6 = $con->prepare("SELECT id,name FROM datasets WHERE link_to=?");
	
		if ($prep_stmt6) {
			my $rc = $prep_stmt6->execute("students");
			if ($rc) {
				while ( my @rslts = $prep_stmt6->fetchrow_array() ) {
					$datasets{$rslts[0]} = $rslts[1];
				}
			}
			else {
				print STDERR "Could not execute SELECT FROM datasets: ", $con->errstr, $/;
			}
		}
		else {
			print STDERR "Could not prepare SELECT FROM datasets: ", $con->errstr, $/;
		}

		$content =
qq*
<!DOCTYPE html>
<HTML lang="en">
<META http-equiv="Content-Type" content="text/html; charset=ISO-8859-1">
<HEAD>
<TITLE>Spanj :: Exam Management Information System :: Upload Fee Balances</TITLE>
</HEAD>
<BODY>
$header
$feedback
*;
		if (scalar(keys %datasets) > 0) {
			$content .= 
qq!<FORM method="POST" action="/cgi-bin/upload_fee_balances.cgi?step=2">
<TABLE>
<TR><TD><LABEL for="dataset">Dataset</LABEL><TD><SELECT name="dataset">
!;
			for my $dataset (keys %datasets) {
				$content .= qq!<OPTION value="$dataset" title="$datasets{$dataset}">$datasets{$dataset}</OPTION>!;
			}
			$content .= qq!
</SELECT>
</TABLE>
<TR><TD colspan="2"><INPUT type="submit" name="continue" value="Continue">
</FORM>
!;
		}
		#no datasets
		else {
			$content .=
qq*
<p><em>No datasets have been uploaded yet.</em> Would you like to <a href="/cgi-bin/datasets.cgi">upload a dataset</a> now?<p>If you have uploaded a dataset but you still encounter this error, ensure that you select 'link to students' DB' and try again.
*;
		}

		$content .= "</BODY></HTML>";

	#}
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

sub htmlspecialchars {
	my $cp = $_[0];
	$cp =~ s/&/&#38;/g;
        $cp =~ s/</&#60;/g;
        $cp =~ s/>/&#62;/g;
        $cp =~ s/'/&#39;/g;
        $cp =~ s/"/&#34;/g;
        return $cp;
}
