#!/usr/bin/perl

use strict;
use warnings;
#no warnings 'uninitialized';

#use feature "switch";

use DBI;
use Fcntl qw/:flock SEEK_END/;
#use Storable qw/freeze thaw/;

require "./conf.pl";

our($db,$db_user,$db_pwd,$log_d,$doc_root,$upload_dir);

my %session;
my %auth_params;

my $logd_in = 0;
my $authd = 0;

my $con;

my $per_page = 10;
my $page = 1;

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

	#per page
	if (exists $session{"per_page"} and $session{"per_page"} =~ /^(\d+)$/) {
		$per_page = $1;
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
	<p><a href="/">Home</a> --&gt; <a href="/administrator.html">Administrator Panel</a> --&gt; <a href="/messenger/">Messenger</a> --&gt; <a href="/cgi-bin/contacts.cgi">Manage List of Contacts</a>
	<hr> 
};

unless ($authd) {
	if ($logd_in) {
		$content .=
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Messenger - Upload Data</title>
</head>
<body>
$header
<p><span style="color: red">Sorry, you do not have the appropriate privileges to manage the list of contacts.</span> Only the administrator is authorized to take this action.
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
		print "Location: /login.html?cont=/cgi-bin/contacts.cgi\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";
       		my $res = 
qq!
<html lang="en">
<head>
<title>Spanj: School Management Information System</title>
</head>
<body>
You should have been redirected to <a href="/login.html?cont=/cgi-bin/contacts.cgi">/login.html?cont=/cgi-bin/contacts.cgi</a>. If you were not, <a href="login.html?cont=/cgi-bin/contacts.cgi">Click Here</a> 
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

my $create_new = 0;
my $directory = undef;
my $edit = 0;
my $add  = 0;
my $search = 0;
my $enc_search_str = "";
my $search_str = "";

my $download = 0;
my $upload = 0;

my $file_id = undef;

if ( exists $ENV{"QUERY_STRING"} ) {
	if ( $ENV{"QUERY_STRING"} =~ /\&?act=new\&?/i ) {
		$create_new++;
	}

	if ( $ENV{"QUERY_STRING"} =~ /\&?act=edit\&?/i ) {
		$edit++;
	}

	if ( $ENV{"QUERY_STRING"} =~ /\&?act=add\&?/i ) {
		$add++;
	}

	if ( $ENV{"QUERY_STRING"} =~ /\&?act=search\&?/i ) {
		$search++;
	}
	if ( $ENV{"QUERY_STRING"} =~ /\&?act=download\&?/i ) {
		$download++;
	}
	if ( $ENV{"QUERY_STRING"} =~ /\&?act=upload(\d)\&?/i ) {
		$upload = $1;
	}

	if ( $ENV{"QUERY_STRING"} =~ /\&?directory=(\d+)\&?/i ) {
		$directory = $1;
	}

	if ( $ENV{"QUERY_STRING"} =~ /\&?pg=(\d+)\&?/ ) {
		$page = $1;
	}

	if ( $ENV{"QUERY_STRING"} =~ /\&?per_page=(\d+)\&?/ ) {	
			my $possib_per_page = $1;
			
			if (($possib_per_page % 10) == 0) { 	
				$per_page = $possib_per_page;
			}
			else {
				if ($possib_per_page < 10) {
					$per_page = 10;
				}
				else {
					$per_page = substr("".$possib_per_page, 0, -1) . "0";
				}
			}
			#when the user changes the results per
			#page to more results per page, they should
			#be sent a page down.
			#if they select fewer results per page, they should
			#be sent a page up.
			$session{"per_page"} = $per_page;	
	}

	if ( $ENV{"QUERY_STRING"} =~ /\&?q=([^\&]+)\&?/ ) {
		$enc_search_str = $1;

		$search_str  = $enc_search_str;
		$search_str =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;

		$search++;
	}
	
}

PM: {
if ($post_mode) {
	#user has just posted a directory name
	#make sure it's not blank || too long
	#save to DB
	my ($name,$pry_key);

	if ($create_new) {
		my @errors = ();

		unless ( exists $session{"confirm_code"} and exists $auth_params{"confirm_code"} and $session{"confirm_code"} eq $auth_params{"confirm_code"} ) {
			push @errors, qq!Invalid authorization token sent. Do not alter the hidden values in this form.!;
		}

		if ( exists $auth_params{"name"} and length($auth_params{"name"}) > 0) {
			$name = $auth_params{"name"};
		}
		else {
			push @errors, qq!No directory name given!;
		}

		if ( exists $auth_params{"pry_key"} and length($auth_params{"pry_key"}) > 0) {	
			$pry_key = $auth_params{"pry_key"};
		}
		else {
			push @errors, qq!No primary/unique key was provided.!;
		}

		if (@errors) {

			if (@errors == 1) {
				$feedback = qq!<span style="color: red">Could not create directory: </span>$errors[0]!;
			}
			else {
				$feedback =
qq!
<span style="color: red">Could not create directory.</span>The Following errors were encountered:

<UL>
!;
				foreach (@errors) { 
					$feedback .= "<LI>$_";
				}

				$feedback .= "</UL>";

				$post_mode = 0;
				last PM;	
			}
		}

		#check if this directory exists.
		my $pre_existing_id = -1;
		my $current_pry_key = undef;
		my $current_num_entries = 0; 

		$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});
		my $prep_stmt1 = $con->prepare("SELECT id,primary_key,num_entries FROM contacts_directories WHERE name=? ORDER BY id DESC LIMIT 1");

		if ($prep_stmt1) {
			my $rc = $prep_stmt1->execute($name);
			if ($rc) {
				while ( my @rslts = $prep_stmt1->fetchrow_array() ) {
					$pre_existing_id = $rslts[0];
					$current_pry_key = $rslts[1];
					$current_num_entries = $rslts[2];
				}
			}
			else {
				print STDERR "Could not execute SELECT id,primary_key,num_entries FROM contacts_directories: ", $con->errstr, $/;
			}
		}
		else {
			print STDERR "Could not prepare SELECT id,primary_key,num_entries FROM contacts_directories: ", $con->errstr, $/;
		}

		my $msg = "";
		#this directory name already exists.
		if ($pre_existing_id > 0) {
			$msg = qq!<p><em>The directory <a href="/cgi-bin/contacts.cgi?directory=$pre_existing_id">! . htmlspecialchars($name) . "</a> already exists. It currently has $current_num_entries entries.</em>";
			#check if the pry key has been updated
			if ( lc($current_pry_key) ne lc($pry_key) )  {
				my $prep_stmt2 = $con->prepare("UPDATE contacts_directories SET primary_key=? WHERE id=? LIMIT 1");

				if ($prep_stmt2) {
					my $rc = $prep_stmt2->execute($pry_key,$pre_existing_id);
					
					if ($rc) {
						$msg .= "<p>However, the directory's primary/unique key has been updated.";
						$con->commit();

						#log create directory
						my @today = localtime;	
						my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];
						
						open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");

       						if ($log_f) {
       							@today = localtime;	
							my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
							flock ($log_f, LOCK_EX) or print STDERR "Could not log update directory for 1 due to flock error: $!$/";
							seek ($log_f, 0, SEEK_END);
				 
							print $log_f "1 UPDATE DIRECTORY $name $time\n";
							flock ($log_f, LOCK_UN);
       							close $log_f;
       						}
						else {
							print STDERR "Could not log create directory for 1: $!\n";
						}
					}
					else {
						print STDERR "Could not execute UPDATE contacts_directories: ", $con->errstr, $/;
					}
				}
				else {
					print STDERR "Could not prepare UPDATE contacts_directories: ", $con->errstr,$/;
				}
			}
		}
		else {
#create this entry.
			my $prep_stmt3 = $con->prepare("INSERT INTO contacts_directories VALUES (NULL,?,?,0)");

			if ($prep_stmt3) {
				my $rc = $prep_stmt3->execute($name, $pry_key);
					
				if ($rc) {
					$msg .= "<p><em>Your directory has been created!</em>";

					#log create directory
					my @today = localtime;	
					my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];
						
					open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");

       					if ($log_f) {
       						@today = localtime;	
						my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
						flock ($log_f, LOCK_EX) or print STDERR "Could not log create directory for 1 due to flock error: $!$/";
						seek ($log_f, 0, SEEK_END);
				 
						print $log_f "1 CREATE DIRECTORY $name $time\n";
						flock ($log_f, LOCK_UN);
       						close $log_f;
       					}
					else {
						print STDERR "Could not log create directory for 1: $!\n";
					}

				}
				else {
					print STDERR "Could not execute INSERT INTO contacts_directories: ", $con->errstr, $/;
				}
			}
			else {
				print STDERR "Could not prepare INSERT INTO contacts_directories: ", $con->errstr,$/;
			}

			$con->commit();

			my $prep_stmt4 = $con->prepare("SELECT id FROM contacts_directories WHERE name=? ORDER BY id DESC LIMIT 1");

			if ($prep_stmt4) {
				my $rc = $prep_stmt4->execute($name);
				if ($rc) {
					my $id = ($prep_stmt4->fetchrow_array())[0];
					$msg .= qq!<p>Would you like to <a href="/cgi-bin/contacts.cgi?directory=$id">edit the new directory</a> now?!;
				}
				else {
					print STDERR "Could not execute SELECT id,primary_key,num_entries FROM contacts_directories: ", $con->errstr, $/;
				}
			}
			else {
				print STDERR "Could not prepare SELECT id,primary_key,num_entries FROM contacts_directories: ", $con->errstr,$/;
			}	
		}
	
		$content = 
qq*
<!DOCTYPE html>
<html lang="en">

<head>

<title>Messenger - Manage List of Contacts - Create New Directory</title>
</head>
<body>
$header
$msg 
</body>
</html>
*;
		
	}

	if ($edit) {
		unless ( exists $session{"confirm_code"} and exists $auth_params{"confirm_code"} and $session{"confirm_code"} eq $auth_params{"confirm_code"} ) {
			$feedback = qq!<p><span style="color: red">Invalid authorization token sent.</span> Do not alter the hidden values in this form.!;
			$post_mode = 0;
			last PM;
		}

		unless (defined $directory) {
			$feedback = qq!<p><span style="color: red">No directory specified.</span>!;
			$post_mode = 0;
			last PM;
		}

		#check if this directory exists
		my ($pry_key, $dir_name) = (undef, undef);

		$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});
		my $prep_stmt8 = $con->prepare("SELECT name,primary_key FROM contacts_directories WHERE id=? LIMIT 1");

		if ($prep_stmt8) {
			my $rc = $prep_stmt8->execute($directory);
			if ($rc) {
				while ( my @rslts = $prep_stmt8->fetchrow_array() ) {
					$dir_name = $rslts[0];
					$pry_key  = $rslts[1];
				}
			}
			else {
				print STDERR "Could not execute SELECT name,primary_key FROM contacts_directories: ", $con->errstr, $/;
			}
		}
		else {
			print STDERR "Could not prepare SELECT name,primary_key FROM contacts_directories: ", $con->errstr,$/;
		}

		unless (defined $pry_key and defined $dir_name) {
			$feedback = qq!<span style="color: red">The directory specified does not exist.</span>!;
			$post_mode = 0;
			last PM; 
		}
		my %successful_edits;
		my $successful_deletes;

		my %errors;

		my %deletes;
		my %edits;

		my ($deletes_cnt, $edits_cnt) = (0,0);

		for my $attrib (keys %auth_params) {

			if ($attrib =~ /^delete[0-9]+$/) {
				$deletes{$auth_params{$attrib}}++;
				$deletes_cnt++;
			}

			elsif ($attrib =~ /^edit([0-9]+)-id$/) {

				my $index = $1;
				my $id = $auth_params{$attrib};	

				$edits{$id} = {};

				$edits_cnt++;

				if (exists $auth_params{"edit${index}-name"}) {
					${$edits{$id}}{"name"} = $auth_params{"edit${index}-name"};
				}

				if (exists $auth_params{"edit${index}-phone_no"}) {
					my $possib_phone_no = $auth_params{"edit${index}-phone_no"};
					if ( $possib_phone_no =~ /^\+?\d+(?:,\+?\d+)*$/ ) {
						${$edits{$id}}{"phone_no"} = $possib_phone_no;
					}
					else {
						${$errors{"Submitted invalid phone number(s)"}}{$id}++;
					}
				}

				#incase JS didn't handle this.
				my @phone_num_bts = ();

				for ( my $i = 1; $i < 5; $i++ ) {
					if ( exists $auth_params{"edit${index}-phone_no-$i"} and length($auth_params{"edit${index}-phone_no-$i"}) > 0) {
						my $possib_num = $auth_params{"edit${index}-phone_no-$i"};
						if ($possib_num =~ /^\+?\d+$/) {
							push @phone_num_bts, $possib_num;
						}
						else {
							${$errors{"Submitted invalid phone number(s)"}}{$id}++;
						}
					}
				}
				if (@phone_num_bts) {
					${$edits{$id}}{"phone_no"} = join(",", @phone_num_bts);
				}
			}
		}

		if ( $deletes_cnt or $edits_cnt ) {
			#you don't want to delete ghosts so
			#check if these entries exist.
			
			my @ids = keys %deletes;
			push(@ids, keys %edits);

			my @ids_placeholders = ();

			foreach (@ids) {
				push @ids_placeholders, "id=?";
			}

			my %existing_ids = ();

			my $ids_placeholders_str = join(" OR ", @ids_placeholders);

			$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

			my $prep_stmt2 = $con->prepare("SELECT id FROM contacts WHERE $ids_placeholders_str");

			if ($prep_stmt2) {
				my $rc = $prep_stmt2->execute(@ids);
				if ($rc) {
					while ( my @rslts = $prep_stmt2->fetchrow_array() ) {
						$existing_ids{$rslts[0]}++;	
					}
				}

				else {
					print STDERR "Could not execute SELECT id FROM contacts: ", $con->errstr, $/;
				}
			}
			else {
				print STDERR "Could not prepare SELECT id FROM contacts: ", $con->errstr,$/;
			}
				

			if ($deletes_cnt) {
				for my $del (keys %deletes) {
					if ( not exists $existing_ids{$del} ) {
						${$errors{"Deleted non-existent entries"}}{htmlspecialchars($del)}++;
						delete $deletes{$del};
						$deletes_cnt--;
					}
				}
			}

			if ($edits_cnt) {
				for my $edit (keys %edits) {
					if ( not exists $existing_ids{$edit} ) {
						${$errors{"Edited non-existent entries"}}{htmlspecialchars($edit)}++;
						delete $edits{$edit};
						$edits_cnt--;
					}
				}
			}
			
			#do actual deleting.
			if ($deletes_cnt) {

				my @dels_placeholders;
				for my $del (keys %deletes) {
					push @dels_placeholders, "id=?";
				}

				my $dels_placeholders_str = join(" OR ", @dels_placeholders);

				my $prep_stmt3 = $con->prepare("DELETE FROM contacts WHERE $dels_placeholders_str LIMIT $deletes_cnt");	

				if ($prep_stmt3) {
					my $rc = $prep_stmt3->execute(keys %deletes);
					if ($rc) {
						$successful_deletes++;

						#log delete contact
						my @today = localtime;	
						my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];
						
						open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");

	       					if ($log_f) {
	       						@today = localtime;	
							my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
							flock ($log_f, LOCK_EX) or print STDERR "Could not log delete contact for 1 due to flock error: $!$/";
							seek ($log_f, 0, SEEK_END);
				
							for my $del (keys %deletes) { 
								print $log_f "1 DELETE CONTACT $del $time\n";
							}

							flock ($log_f, LOCK_UN);
	       						close $log_f;
	       					}
						else {
							print STDERR "Could not log delete contact for 1: $!\n";
						}

						#update directories num_entries
						my $prep_stmt7 = $con->prepare("UPDATE contacts_directories SET num_entries=num_entries - $deletes_cnt WHERE id=?");

						if ($prep_stmt7) {
							my $rc = $prep_stmt7->execute($directory);
							if ($rc) {


							}
							else {
								print STDERR "Could not execute UPDATE contacts_directories: ", $con->errstr, $/;
							}
						}
						else {
							print STDERR "Could not prepare UPDATE contacts_directories: ", $con->errstr,$/;
						}
					}
					else {
						print STDERR "Could not execute DELETE contacts: ", $con->errstr, $/;
					}
				}
				else {
					print STDERR "Could not prepare DELETE FROM contacts: ", $con->errstr,$/;
				}
				$con->commit();
			}

			if ($edits_cnt) {
				my @update_name = ();
				my @update_phone_no = ();
				my @update_both = ();	

				for my $edit (keys %edits) {
					if ( exists ${$edits{$edit}}{"name"} and not exists ${$edits{$edit}}{"phone_no"} ) {
						push @update_name, $edit;	
					}
					elsif ( not exists ${$edits{$edit}}{"name"} and exists ${$edits{$edit}}{"phone_no"} ) {
						push @update_phone_no, $edit;	
					}

					elsif ( exists ${$edits{$edit}}{"name"} and exists ${$edits{$edit}}{"phone_no"} ) {
						push @update_both, $edit;	
					}
				}

		
				if (@update_name) {
					my $prep_stmt4 = $con->prepare("UPDATE contacts SET name=? WHERE id=? LIMIT 1");
					if ($prep_stmt4) {
						for (my $i = 0; $i < scalar(@update_name); $i++) {
							my $rc = $prep_stmt4->execute(${$edits{$update_name[$i]}}{"name"}, $update_name[$i]);
							if ($rc) {
								$successful_edits{$update_name[$i]}++;
							}
							else {
								print STDERR "Could not execute UPDATE contacts: ", $con->errstr, $/;
							}
						}
					}
					else {
						print STDERR "Could not prepare UPDATE contacts: ", $con->errstr,$/;
					}
				}

				if (@update_phone_no) {	
					my $prep_stmt5 = $con->prepare("UPDATE contacts SET phone_no=? WHERE id=? LIMIT 1");
					if ($prep_stmt5) {
						for (my $i = 0; $i < scalar(@update_phone_no); $i++) {
							my $rc = $prep_stmt5->execute(${$edits{$update_phone_no[$i]}}{"phone_no"}, $update_phone_no[$i]);
							if ($rc) {
								$successful_edits{$update_phone_no[$i]}++;
							}
							else {
								print STDERR "Could not execute UPDATE contacts: ", $con->errstr, $/;
							}
						}
					}
					else {
						print STDERR "Could not prepare UPDATE contacts: ", $con->errstr,$/;
					}
				}

				if (@update_both) {	
					my $prep_stmt6 = $con->prepare("UPDATE contacts SET name=?,phone_no=? WHERE id=? LIMIT 1");
					if ($prep_stmt6) {
						for (my $i = 0; $i < scalar(@update_phone_no); $i++) {
							my $rc = $prep_stmt6->execute(${$edits{$update_both[$i]}}{"name"}, ${$edits{$update_both[$i]}}{"phone_no"}, $update_both[$i]);
							if ($rc) {
								$successful_edits{$update_both[$i]}++;
							}
							else {
								print STDERR "Could not execute UPDATE contacts: ", $con->errstr, $/;
							}
						}
					}
					else {
						print STDERR "Could not prepare UPDATE contacts: ", $con->errstr,$/;
					}
				}
				$con->commit();
			}
		}


		if (keys %successful_edits) {
			#log edit contact
			my @today = localtime;	
			my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];
						
			open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");

			if ($log_f) {
				@today = localtime;	
				my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
				flock ($log_f, LOCK_EX) or print STDERR "Could not log edit contact for 1 due to flock error: $!$/";
				seek ($log_f, 0, SEEK_END);
				
				for my $edit (keys %successful_edits) { 
					print $log_f "1 EDIT CONTACT $edit $time\n";
				}

				flock ($log_f, LOCK_UN);
				close $log_f;
			}
			else {
				print STDERR "Could not log edited contact for 1: $!\n";
			}
		}

		if ($successful_deletes) {
			$feedback .= qq!<p>Directory ! . htmlspecialchars($dir_name) . qq! has been altered. The following ! . htmlspecialchars(${pry_key}) . qq!/s were <span style="color: green">successfully deleted</span>: ! . htmlspecialchars(join(", ", keys %deletes)); 
		}

		if ( keys %successful_edits ) {
			$feedback .= qq!<p>Directory ! . htmlspecialchars($dir_name) . qq! has been updated.The following ! . htmlspecialchars(${pry_key}) . qq!/s were <span style="color: green">successfully edited</span>: ! . htmlspecialchars(join(", ", keys %successful_edits)); 
		}

		if (keys %errors) {
			$feedback .= qq!<p>Some errors were experienced while processing the data posted:<UL>!;
			foreach (keys %errors) {
				$feedback .= '<LI>' . $_ . ": " . htmlspecialchars(join(", ", keys %{$errors{$_}})); 
			}
			$feedback .= "</UL>";
		}
		$post_mode = 0;
		last PM;
	}

	if ($add) {

		my ($dir_name, $pry_key);
		unless ( exists $session{"confirm_code"} and exists $auth_params{"confirm_code"} and $session{"confirm_code"} eq $auth_params{"confirm_code"} ) {
			$feedback = qq!<p><span style="color: red">Invalid authorization token sent.</span> Do not alter the hidden values in this form.!;
			$post_mode = 0;
			last PM;
		}

		unless (defined $directory) {
			$feedback = qq!<p><span style="color: red">No directory specified.</span>!;
			$post_mode = 0;
			last PM;
		}

		$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});
		my $prep_stmt8 = $con->prepare("SELECT name,primary_key FROM contacts_directories WHERE id=? LIMIT 1");

		if ($prep_stmt8) {
			my $rc = $prep_stmt8->execute($directory);
			if ($rc) {
				while ( my @rslts = $prep_stmt8->fetchrow_array() ) {	
					$dir_name = $rslts[0];
					$pry_key  = $rslts[1];
				}
			}
			else {
				print STDERR "Could not execute SELECT name,primary_key FROM contacts_directories: ", $con->errstr, $/;
			}
		}
		else {
			print STDERR "Could not prepare SELECT name,primary_key FROM contacts_directories: ", $con->errstr, $/;
		}

		unless (defined $pry_key and defined $dir_name) {
			$feedback = qq!<span style="color: red">The directory specified does not exist.</span>!;
			$post_mode = 0;
			last PM; 
		}

		my %adds;
		my %errors;
		my $adds_cnt = 0;

		for my $attrib (keys %auth_params) {

			if ($attrib =~ /^add([0-9]+)-id$/) {

				my $index = $1;
				my $id = $auth_params{$attrib};	

				$adds{$id} = {};

				$adds_cnt++;

				if ( exists $auth_params{"add${index}-name"} and length($auth_params{"add${index}-name"}) > 0 ) {
					${$adds{$id}}{"name"} = $auth_params{"add${index}-name"};
				}
				else {
					delete $adds{$id};
					${$errors{"No name provided."}}{$id}++;
				}

				if (exists $auth_params{"add${index}-phone_no"}) {
					my $possib_phone_no = $auth_params{"add${index}-phone_no"};
					if ( $possib_phone_no =~ /^\+?\d+(?:,\+?\d+)*$/ ) {
						${$adds{$id}}{"phone_no"} = $possib_phone_no;
					}
					else {
						delete $adds{$id};
						${$errors{"Submitted invalid phone number(s)"}}{$id}++;
					}
				}

				#incase JS didn't handle this.
				my @phone_num_bts = ();
				my $non_js = 0;

				for ( my $i = 1; $i < 5; $i++ ) {
					if ( exists $auth_params{"add${index}-phone_no-$i"} and length($auth_params{"edit${index}-phone_no-$i"}) > 0) {
						$non_js++;
						my $possib_num = $auth_params{"edit${index}-phone_no-$i"};
						if ($possib_num =~ /^\+?\d+$/) {
							push @phone_num_bts, $possib_num;
						}
						else {
							${$errors{"Submitted invalid phone number(s)"}}{$id}++;
						}
					}
				}
				if (@phone_num_bts) {
					${$adds{$id}}{"phone_no"} = join(",", @phone_num_bts);
				}
				#was expecting a phone no. I didn't get it.
				elsif ($non_js) {
					delete $adds{$id};
				}
			}
		}
		
		my $num_adds = scalar(keys %adds);

		my $successful_adds = 0;

		if ($num_adds) {

			my @insert_placeholders;
			my @insert_values;

			for my $add_id (keys %adds) {

				my $name  = ${$adds{$add_id}}{"name"};
				my $phone_no = ${$adds{$add_id}}{"phone_no"};

				push @insert_placeholders, "(?,?,?,?)";
				push @insert_values, ($add_id, $name, $phone_no, $directory);

			}

			my $insert_placeholders_str = join(", ", @insert_placeholders);

			my $prep_stmt8 = $con->prepare("REPLACE INTO contacts VALUES $insert_placeholders_str");	

			if ($prep_stmt8) {
				my $rc = $prep_stmt8->execute(@insert_values);
				if ($rc) {
					$successful_adds++;
					#update directories num_entries
					my $prep_stmt9 = $con->prepare("UPDATE contacts_directories SET num_entries=num_entries + $num_adds WHERE id=?");

					if ($prep_stmt9) {
						my $rc = $prep_stmt9->execute($directory);
						unless ($rc) {
							print STDERR "Could not execute UPDATE contacts_directories: ", $con->errstr, $/;
						}
					}
					else {
						print STDERR "Could not prepare UPDATE contacts_directories: ", $con->errstr, $/;
					}
				}
				else {
					print STDERR "Could not execute REPLACE INTO contacts: ", $con->errstr, $/;
				}
			}
			else {
				print STDERR "Could not prepare REPLACE INTO contacts: ", $con->errstr, $/;
			}
			$con->commit();
		}

		if ($successful_adds) {
			$feedback .= qq!<p>Directory ! . htmlspecialchars($dir_name) . qq! has been altered. The following ! . htmlspecialchars(${pry_key}) . qq!/s were <span style="color: green">successfully added</span>: ! . htmlspecialchars(join(", ", keys %adds)); 

			#log add contact
			my @today = localtime;	
			my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];
						
			open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");

			if ($log_f) {
				@today = localtime;	
				my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
				flock ($log_f, LOCK_EX) or print STDERR "Could not log add contact for 1 due to flock error: $!$/";
				seek ($log_f, 0, SEEK_END);
				
				for my $add (keys %adds) { 
					print $log_f "1 ADD CONTACT $add $time\n";
				}

				flock ($log_f, LOCK_UN);
				close $log_f;
			}
			else {
				print STDERR "Could not log add contact for 1: $!\n";
			}
		}

		if (keys %errors) {
			$feedback .= qq!<p>Some errors were experienced while processing the data posted:<UL>!;
			foreach (keys %errors) {
				$feedback .= '<LI>' . $_ . ": " . htmlspecialchars(join(", ", keys %{$errors{$_}})); 
			}
			$feedback .= "</UL>";
		}

		$post_mode = 0;
		last PM;
	}
	if ($search) {
		unless ( exists $session{"confirm_code"} and exists $auth_params{"confirm_code"} and $session{"confirm_code"} eq $auth_params{"confirm_code"} ) {
			$feedback = qq!<p><span style="color: red">Invalid authorization token sent.</span> Do not alter the hidden values in this form.!;
			$post_mode = 0;
			last PM;
		}

		unless (defined $directory) {
			$feedback = qq!<p><span style="color: red">No directory specified.</span>!;
			$post_mode = 0;
			last PM;
		}

		if (exists $auth_params{"search"}) {
			my $possib_search_str = $auth_params{"search"};
			my $len = length($possib_search_str);

			if ( $len > 0 ) {

				$search_str = $possib_search_str;
			
				for (my $i = 0; $i < $len; $i++) {
					my $char = substr($search_str, $i, 1);
					my $char_ord = ord($char);
					$enc_search_str .= sprintf("%%%02X", $char_ord);
				}

			}
			else {
				$search = 0;
			}
		}
		else {
			$search = 0;
		}
		$post_mode = 0;
		last PM;
	}

	#user has uploaded a file
	if ($upload == 2) {
			
		unless ($multi_part) {
			$post_mode = 0;
			$upload = 1;
			$feedback = qq!<p><span style="color: red">Invalid request received.</span>!;
			last PM; 
		}

		my $default_line_sep = $/;
		$/ = "\r\n";	

		my $stage = 0;
		my $current_form_var = undef;
		my $current_form_var_content = "";

		my $form_var = 0;
		my $file_var = 0;
		
		my $write = 0;
		my $fh = undef;
		my $dir_lock = undef;	

		my $success = 0;
		my $lines = 0;

		#check for the highest id
		#of file uploaded so far.
		my $max_id = -1;
		open ($dir_lock, ">>$upload_dir/.dir_lock");

       		if ($dir_lock) {
        		flock ($dir_lock, LOCK_EX) or print STDERR "Lock error on upload dir_lock: $!$/";

			opendir(my $uploads, "$upload_dir");
			my @files = readdir($uploads);

			F: foreach (@files) {	
				if ($_ =~ /^(\d+)$/) {
					my $f_id = $1;
					$max_id = $f_id if ($f_id > $max_id);
				}
				else {
					next;
				}
			}

			$file_id = $max_id + 1;

			closedir $uploads;
			flock ($dir_lock, LOCK_UN);
                	close $dir_lock;
			$dir_lock = undef;
		}
		else {
			print STDERR "Could not acquire lock for max(file_id) operation.\n";
			$post_mode = 0;
			$upload = 1;
			$feedback = qq!<p><span style="color: red">Error while saving sent file.</span> Maybe you should retry the operation.!;
			last PM;
		}
	
		my $cntr = 0;
		my $oct_stream = 0;

		while (<STDIN>) {

			if ($_ =~ /$boundary/) {
				if ($form_var) {	
					if (defined $current_form_var) {
						chomp $current_form_var_content;
						$auth_params{$current_form_var} = $current_form_var_content;
					}

					$current_form_var = undef;
					$current_form_var_content = "";
				}
				elsif ($file_var) {
					if (defined $fh) {
						close $fh;
						$fh = undef;
					}
					if (defined $dir_lock) {
						flock ($dir_lock, LOCK_UN);
                				close $dir_lock;
						$dir_lock = undef;	
					}
				}
				$form_var = 0;
				$file_var = 0;
				$stage = 1;
				$write = 0;	
				next;
			}

			if ($write) {	
				$cntr++;
				if ($form_var) {
					chomp $_;
					$current_form_var_content .= $_;	
				}

				elsif ($file_var) {
					#ignore the final blank.
					next if ( $_ eq "\r\n" or $_ eq "\n");

					$_ =~ s/\r\n/\n/g;

					print $fh $_;
				}
				next;
			}
			if ($stage == 1) {
				if ($_ =~ /^Content-Disposition:\s*form-data;\s*name="csv_file"/) {	
					$file_var = 1;
				}
				elsif ($_ =~ /^Content-Disposition:\s*form-data;\s*name="([^"]+)"/) {	
					$current_form_var = $1;
					$form_var = 1;
				}
				$stage = 2;
				next;
			}
			if ($stage == 2) {
				if ($form_var) {
					if ( $_ eq "\n" or $_ eq "\r\n" ) {
						$write = 1;
					}
				}
				if ($file_var) {
					#found out that Firefox doesn't bother
					#with heuristics to determine file types--
					#it just uses the file extension. If no file
					#extension is given, use 'application/octet-stream'
					#Creates probs for files without an extension
					if ($_ =~ m!^Content-Type:\s*text/(?:(?:plain)|(?:csv))!) {	
						$stage = 3;
					}
					elsif ($_ =~ m!^Content-Type:\s*application/octet-stream!) {
						$stage = 3;
						$oct_stream++;
					}
					else {
						$post_mode = 0;
						$upload = 1;
						$feedback = qq!<p><span style="color: red">Upload failed: the file selected is not a text file.</span> Messeger only accepts data as CSV text files.!;
						last PM;
					}
				}
				next;
			}
			if ($stage == 3) {
				if ($_ eq "\n" or $_ eq "\r\n") {	
					open ($fh, ">$upload_dir/$file_id") or print STDERR "Could not open uploads dir for writing:$!$/";
			
					$write = 1;
					$success++;	
				}
				next;
			}
		}

		if ($success) {
			if ($oct_stream) {
				unless (-T "$upload_dir/$file_id") {
					$post_mode = 0;
					$upload = 1;
					$feedback = qq!<p><span style="color: red">Upload failed: the file selected is not a text file.</span> Messeger only accepts data as CSV text files.!;
					last PM;
				}
			}
		}
		else {
			$post_mode = 0;
			$upload = 1;
			$feedback = qq!<span style="color: red">Error saving uploaded file.</span> The data has not been saved.!;
			last PM;	
		}
	
		unless (exists $auth_params{"confirm_code"} and exists $session{"confirm_code"} and ($auth_params{"confirm_code"} eq $session{"confirm_code"})) {
			$feedback = qq!<p><span style="color: red">Invalid request sent.</span> Do not alter the values in the HTML form.!;
				
			#if this request was invalid;
			#delete the uploaded file.
			unlink "$upload_dir/$file_id";

			$post_mode = 0;
			$upload = 1;
			last PM;
		}

		#user has uploaded a contacts file
		if ($success) {
			#log upload contacts
			my @today = localtime;	
			my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];
						
			open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");

			if ($log_f) {
				@today = localtime;	
				my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
				flock ($log_f, LOCK_EX) or print STDERR "Could not log upload contacts for 1 due to flock error: $!$/";
				seek ($log_f, 0, SEEK_END);
					
				print $log_f "1 UPLOAD CONTACTS $file_id $time\n";
	
				flock ($log_f, LOCK_UN);
				close $log_f;
			}
			else {
				print STDERR "Could not log upload contacts for 1: $!\n";
			}
		}
		#now preview data;
		#ask user for any links
		#get foreign key.
		$/ = $default_line_sep;
	
		$post_mode = 0;
		last PM;		
	}

	#user has sent over a file_id, has_header and the dataset column to DB field conversations.
	if ($upload == 3) {

		#check if this directory exists
		my ($pry_key, $dir_name) = (undef, undef);

		$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});
		my $prep_stmt8 = $con->prepare("SELECT name,primary_key FROM contacts_directories WHERE id=? LIMIT 1");

		if ($prep_stmt8) {
			my $rc = $prep_stmt8->execute($directory);
			if ($rc) {
				while ( my @rslts = $prep_stmt8->fetchrow_array() ) {
					$dir_name = htmlspecialchars($rslts[0]);
					$pry_key  = htmlspecialchars($rslts[1]);
				}
			}
			else {
				print STDERR "Could not execute SELECT name,primary_key FROM contacts_directories: ", $con->errstr, $/;
			}
		}
		else {
			print STDERR "Could not prepare SELECT name,primary_key FROM contacts_directories: ", $con->errstr, $/;
		}

		unless (defined $pry_key and defined $dir_name) {
			$feedback = qq!<span style="color: red">The directory specified does not exist.</span>!;	
			$upload = 0;
			last PM; 
		}

		$file_id = undef;

		my $largest_col = -1;

		my $has_header = 0;
		my (%column_to_field, %field_to_column);

		if (exists $auth_params{"file_id"}) {
			$file_id = $auth_params{"file_id"};

			if ($file_id =~ /^\d+$/) {
				if (-e "$upload_dir/$file_id") {
					
					if (exists $auth_params{"has_header"} and $auth_params{"has_header"} eq "1") {
						$has_header = 1;
					}

					#name
					if (exists $auth_params{"id_column"}) {

						my $id_column = $auth_params{"id_column"};

						if ( $id_column =~ /^\d+$/ ) {
	
							if (exists $column_to_field{$id_column}) {
								$feedback = qq!<span style="color: red">Column $id_column selected for multiple fields.</span>!;
								$upload = 2;
							}
							else {
								$column_to_field{$id_column} = "id";
								$field_to_column{"id"} = $id_column;

								$largest_col = $id_column if ($id_column > $largest_col);
								#name
								if (exists $auth_params{"name_column"}) {

									my $name_column = $auth_params{"name_column"};

									if ( $name_column =~ /^\d+$/ ) {
	
										if (exists $column_to_field{$name_column}) {
											$feedback = qq!<span style="color: red">Column $name_column selected for multiple fields.</span>!;
											$upload = 2;
										}
										else {
											$column_to_field{$name_column} = "name";
											$field_to_column{"name"} = $name_column;

											$largest_col = $name_column if ($name_column > $largest_col);
											#phone_no
											if (exists $auth_params{"phone_no_column"}) {
	
												my $phone_no_column = $auth_params{"phone_no_column"};

												if ( $phone_no_column =~ /^\d+$/ ) {
	
													if (exists $column_to_field{$phone_no_column} and $column_to_field{$phone_no_column} ne "phone_no") {
														$feedback = qq!<span style="color: red">Column $phone_no_column selected for multiple fields.</span>!;
														$upload = 2;
													}
													else {
														$column_to_field{$phone_no_column} = "phone_no";

														if ( not exists $field_to_column{"phone_no"} ) {
															$field_to_column{"phone_no"} = [];
														}

														push @{$field_to_column{"phone_no"}}, $phone_no_column;

														$largest_col = $id_column if ($phone_no_column > $largest_col);
													}
												}
												else {
													$feedback = qq!<span style="color: red">Invalid column selected for the phone number(s) field.</span>!;
													$upload = 2;
												}
											}
										}
									}
									else {
										$feedback = qq!<span style="color: red">Invalid column selected for the name field.</span>!;
										$upload = 2;
									}
								}
							}

						}
						else {
							$feedback = qq!<span style="color: red">Invalid column selected for the $pry_key.</span>!;
							$upload = 2;
						}
					}
				}
				else {
					$feedback = qq!<span style="color: red">Unknown file id posted.</span>!;
					$upload = 2;
				}
			}
			else {
				$feedback = qq!<p><span style="color: red">Invalid file id posted.</span>!;
				$upload = 2;
			}
		}
		else {
			$feedback = qq!<p><span style="color: red">No file id posted.</span>!;
			$upload = 2;
		}
		#passed validity checks.
		if ($upload == 3) {
			#read file, load data.
			#distinguish updates from inserts

			my %data;
			my %errors;
			
			open (my $f, "<$upload_dir/$file_id");
		
			#my @header_cols = ();

			my $lines = 0;

			while (<$f>) {
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
					#assume that brackets will be employed around
					#an entire field
					#has it been opened?
					if ($cols[$i] =~ /^".*/) {
						#has it been closed?
						my $closed = 1;

						#does not end with brackets? not closed
						if ( $cols[$i] !~ /"$/ ) {
							$closed = 0;
						}

						#end with a single backstroke-escaped quote
						elsif ( $cols[$i] =~ /[^\\]?\\"$/ ) {
							$cols[$i] =~ s/\\"/"/;
							$closed = 0;
						}
						
						unless ( $closed ) {
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
						$cols[$j] =~ s/\\"/"/g; 
					}
				}

				#data must have atleast 3 columns
				my $num_cols = scalar(@cols);

				if ($num_cols < $largest_col) {
					$feedback = qq!<p><span style="color: red">One or more of the columns you requested do not exist in the data file.</span>!;
					$upload = 2;
					last;
				}

				if ($lines == 1) {
					if (not $has_header) {
						next;
					}
				}

				
				my $id = $cols[$field_to_column{"id"}];

				#valid ID
				if (defined $id and length($id) > 0) {

					my $name = $cols[$field_to_column{"name"}];

					if (length($name) > 0) {

						my @phone_nos = ();
						my @phone_no_cols = @{$field_to_column{"phone_no"}};

						for ( my $k = 0; $k < @phone_no_cols; $k++ ) {

							my $phone_no = $cols[$phone_no_cols[$k]];

							if ( $phone_no =~ /^\+?\d+(?:([^0-9])\+?\d+)*$/ ) {

								my $separator = $1;

								if ( defined $separator and length($separator) > 0 ) {
									my @phone_nos_bts = split/$separator/,$phone_no;
									push @phone_nos, @phone_nos_bts;
								}

								else {
									push @phone_nos, $phone_no;
								}
							}
							else {
								${$errors{"Invalid phone number(s)"}}{htmlspecialchars($id)}++;
							}
						}

						if (scalar(@phone_nos) > 0) {
							my $phone = join(",", @phone_nos);
							$data{$id} = {"name" => $name, "phone_no" => $phone};
						}
					}

					else {
						${$errors{"Blank name"}}{htmlspecialchars($id)}++;
					}
				}
				else {
					#shady way to handle a bad data structure.
					#it had to be a hash of hashrefs.
					#yet a hash would do in in this case.
					if (not exists $errors{"Blank $pry_key"}) {
						$errors{"Blank $pry_key"} = {1 => 1};
					}
					else {
						for my $entry (keys %{$errors{"Blank $pry_key"}}) {
							my $new_num_entries = $entry + 1;
							$errors{"Blank $pry_key"} = {$new_num_entries => 1};
						}
					}
				}
			}

			my $num_entries = scalar(keys %data);
			if ($num_entries > 0) {
				my @where_clause_bts = ();

				for my $id (keys %data) {
					push @where_clause_bts, "id=?";	
				}

				my $where_clause = join(" OR ", @where_clause_bts);

				my %pre_existing = ();

				my $prep_stmt0 = $con->prepare("SELECT id FROM contacts WHERE directory=? AND ($where_clause) LIMIT $num_entries");

				if ($prep_stmt0) {
					my $rc = $prep_stmt0->execute($directory, keys %data);
					if ($rc) {
						while ( my @rslts = $prep_stmt0->fetchrow_array() ) {
							$pre_existing{$rslts[0]}++;
						}
					}
					else {
						print STDERR "Could not execute SELECT FROM contacts: ", $con->errstr, $/;
					}
				}
				else {
					print STDERR "Could not prepare SELECT FROM contacts: ", $con->errstr, $/;
				}

				#add to feedback
				my $num_edits = 0;

				if (keys %pre_existing) {
					my @successful_edits;
					my $prep_stmt6 = $con->prepare("UPDATE contacts SET name=?,phone_no=? WHERE id=? LIMIT 1");
					if ($prep_stmt6) {
						for my $id (keys %pre_existing) {
							my $rc = $prep_stmt6->execute(${$data{$id}}{"name"}, ${$data{$id}}{"phone_no"}, $id);
							if ($rc) {
								push @successful_edits, $id;
								$num_edits++;
							}
							else {
								print STDERR "Could not execute UPDATE contacts: ", $con->errstr, $/;
							}
							delete $data{$id};
						}
					}
					else {
						print STDERR "Could not prepare UPDATE contacts: ", $con->errstr, $/;
					}

					if (@successful_edits) {

						$feedback .= qq!<p><em>The following $pry_key/s were <span style="color: green">successfully updated</span></em>: ! . htmlspecialchars(join(", ", @successful_edits));

						#log add contact
						my @today = localtime;	
						my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];
						
						open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");

						if ($log_f) {
							@today = localtime;	
							my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
							flock ($log_f, LOCK_EX) or print STDERR "Could not log edit contact for 1 due to flock error: $!$/";
							seek ($log_f, 0, SEEK_END);
				
							for my $edit (@successful_edits) { 
								print $log_f "1 EDIT CONTACT $add $time\n";
							}

							flock ($log_f, LOCK_UN);
							close $log_f;
						}
						else {
							print STDERR "Could not log edit contact for 1: $!\n";
						}

					}
				}

				my @insert_placeholders;
				my @insert_values;

				my $num_adds = scalar(keys %data);

				if ($num_adds > 0) {

					my @successful_adds;

					for my $id (keys %data) {

						my $name  = ${$data{$id}}{"name"};
						my $phone_no = ${$data{$id}}{"phone_no"};
		
						push @insert_placeholders, "(?,?,?,?)";
						push @insert_values, ($id, $name, $phone_no, $directory);
						
						push @successful_adds, htmlspecialchars($id);
					}

					my $insert_placeholders_str = join(", ", @insert_placeholders);

					my $prep_stmt8 = $con->prepare("REPLACE INTO contacts VALUES $insert_placeholders_str");	

					if ($prep_stmt8) {
						my $rc = $prep_stmt8->execute(@insert_values);
						if ($rc) {

							#log add contact
							my @today = localtime;	
							my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];
						
							open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");

							if ($log_f) {
								@today = localtime;	
								my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];

								flock ($log_f, LOCK_EX) or print STDERR "Could not log add contact for 1 due to flock error: $!$/";
								seek ($log_f, 0, SEEK_END);
				
								for my $add (keys %data) { 
									print $log_f "1 ADD CONTACT $add $time\n";
								}

								flock ($log_f, LOCK_UN);
								close $log_f;
							}
							else {
								print STDERR "Could not log add contact for 1: $!\n";
							}

							$feedback .= qq!<p><em>The following $pry_key/s were <span style="color: green">successfully added</span></em>: ! . join(", ", @successful_adds);
							#update directories num_entries
							my $prep_stmt9 = $con->prepare("UPDATE contacts_directories SET num_entries=num_entries + $num_adds WHERE id=?");
	
							if ($prep_stmt9) {
								my $rc = $prep_stmt9->execute($directory);
								unless ($rc) {
									print STDERR "Could not execute UPDATE contacts_directories: ", $con->errstr, $/;
								}
							}
							else {
								print STDERR "Could not prepare UPDATE contacts_directories: ", $con->errstr, $/;
							}

						}
						else {
							print STDERR "Could not execute REPLACE INTO contacts: ", $con->errstr, $/;
						}
					}
					else {
						print STDERR "Could not prepare REPLACE INTO contacts: ", $con->errstr, $/;
					}

				}

				if ($num_adds > 0 or $num_edits > 0) { 
					$con->commit();
					$upload = 0;
				}
			}
		}
		$post_mode = 0;
		last PM;
	}
}
$con->commit();
}

if ( not $post_mode ) {

	$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

	my %directories = ();

	my $prep_stmt0 = $con->prepare("SELECT id,name,primary_key,num_entries FROM contacts_directories");
	if ($prep_stmt0) {
		my $rc = $prep_stmt0->execute();
		if ($rc) {
			while ( my @rslts = $prep_stmt0->fetchrow_array() ) {
				$directories{$rslts[0]} = {"name" => $rslts[1], "pry_key" => $rslts[2], "num_entries" => $rslts[3]};
			}
		}
		else {
			print STDERR "Could not execute SELECT id,name FROM contacts_directories: ", $con->errstr, $/;
		}
	}
	else {
		print STDERR "Could not prepare SELECT id,name FROM contacts_directories: ", $con->errstr, $/;
	}

	#user wants to create a new directory.
	if ( $create_new ) {

		my $conf_code = gen_token();
		$session{"confirm_code"} = $conf_code;

		my @directories_js_array = ();
		
		foreach ( keys %directories ) {
			push @directories_js_array, '"' . lc(${$directories{$_}}{"name"}) . '"';
		}

		my $directories_js_str = "[" . join(", ", @directories_js_array) . "]";

		$content =
qq*
<!DOCTYPE html>
<html lang="en">

<head>

<title>Messenger - Manage List of Contacts - Create New Directory</title>

<SCRIPT type="text/javascript">

var existing_directories = $directories_js_str;
 
function disable_submit() {
	document.getElementById("submit_create").disabled = 1;
}

function dir_name_changed() {

	var dir_name = document.getElementById("directory_name").value.toLowerCase();	
	var pry_key = document.getElementById("directory_pry_key").value;

	var exists = false; 

	for ( var i = 0; i < existing_directories.length; i++ ) {
		if ( dir_name == existing_directories[i] ) {
			exists = true;
			break;
		}
	}

	if (exists) {
		document.getElementById("pre_existing_directory_err").innerHTML = 'A directory with this name already exists';
		document.getElementById("pre_existing_directory_err_asterisk").innerHTML = '\*';
	}
	else {
		document.getElementById("pre_existing_directory_err"). innerHTML = '';
		document.getElementById("pre_existing_directory_err_asterisk").innerHTML = '';
	}

	if ( dir_name.length > 0 && pry_key.length > 0 ) {
		document.getElementById("submit_create").title = "";
		document.getElementById("submit_create").disabled = 0;	
	}

	else {
		document.getElementById("submit_create").title = "Provide a name & Primary/Unique Key to enable";
		document.getElementById("submit_create").disabled = 1;
	}
}

</SCRIPT>

</head>

<body onload="disable_submit()">

$header
<p>$feedback
<p>Create a new directory for your contacts by filling this form and clicking 'Create Directory'.
<p>NOTE: The Primary/Unique Key is a something like an <em>ID Number</em> that is unique for every entry in the directory. This is necessary in order to use <a href="/cgi-bin/datasets.cgi">datasets</a> for message composition.

<FORM method="POST" action="/cgi-bin/contacts.cgi?act=new">

<INPUT type="hidden" name="confirm_code" value="$conf_code">
 
<TABLE>

<TR>
<TD><span style="color: red" id="pre_existing_directory_err_asterisk"></span><LABEL for="name">Directory Name</LABEL>
<TD><INPUT type="text" name="name" id="directory_name" value="" size="20" maxlength="32" onmousemove="dir_name_changed()" onkeyup="dir_name_changed()">

<TR>
<TD colspan="2" style="color: red">
<span id="pre_existing_directory_err"></span>

<TR>
<TD><LABEL for="pry_key">Primary/Unique Key</LABEL>
<TD><INPUT type="text" name="pry_key" id="directory_pry_key" value="" size="20" maxlength="32" onmousemove="dir_name_changed()"  onkeyup="dir_name_changed()">

<TR>
<TD colspan="2"><INPUT type="submit" name="create" value="Create Directory" id="submit_create">

</TABLE>

</FORM>
*;
	}

	#user wants to download this.
	elsif ($download and defined $directory and exists $directories{$directory}) {

		my $line_sep = "\n";
		#change line separator for windows
		if ( exists $ENV{"HTTP_USER_AGENT"} ) {
			my $ua = $ENV{"HTTP_USER_AGENT"};
			if ($ua =~ /windows/i) {
				$line_sep = "\r\n";
			}
		}

		my $csv_data = qq!"${$directories{$directory}}{"pry_key"}","Name","Phone Number(s)"\n!;;
	
		my $prep_stmt0 = $con->prepare("SELECT id,name,phone_no FROM contacts WHERE directory=? ORDER BY id ASC");
		if ($prep_stmt0) {
			my $rc = $prep_stmt0->execute($directory);
			if ($rc) {
				while ( my @rslts = $prep_stmt0->fetchrow_array() ) {
					$csv_data .= qq!"$rslts[0]","$rslts[1]","$rslts[2]"$line_sep!;
				}
			}
			else {
				print STDERR "Could not execute SELECT FROM contacts: ", $con->errstr, $/;
			}
		}
		else {
			print STDERR "Could not prepare SELECT FROM contacts: ", $con->errstr, $/;
		}

		my $f_name = ${$directories{$directory}}{"name"};
		#get rid of any non-alnum chars
		#to avoid OSs tht are too 'partickler'
		#about filenames.
		$f_name =~ s/[^0-9a-zA-Z]/_/g;

		print "Status: 200 OK\r\n";
		print "Content-Type: text/csv; charset=UTF-8\r\n";
	
		my $len = length($csv_data);
		print "Content-Length: $len\r\n";
		print qq!Content-Disposition: attachment; filename="$f_name.csv"\r\n!;
		
		my @new_sess_array = ();

		for my $sess_key (keys %session) {
			push @new_sess_array, $sess_key."=".$session{$sess_key};        
		}
		my $new_sess = join ('&',@new_sess_array);

		print "X-Update-Session: $new_sess\r\n";

		print "\r\n";
		print $csv_data;

		$con->disconnect() if (defined $con and $con);	
		exit 0;
	}

	elsif ($upload == 2 and defined $directory and exists $directories{$directory} and defined $file_id)  {

		my $dir_name = htmlspecialchars(${$directories{$directory}}{"name"});
		my $pry_key = htmlspecialchars(${$directories{$directory}}{"pry_key"});

		open (my $f, "<$upload_dir/$file_id");

		my $table = 
qq*
<TABLE border="1">
*;	
	
		my $num_cols = 0;
		my @header_cols = ();

		my ($lines, $cntr) = (0,0);

		while (<$f>) {
			chomp;
			$lines++;
			#only want user to preview 1st 10 data rows + header
			next if ($cntr++ > 9);
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
				#assume that brackets will be employed around
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
					$cols[$j] =~ s/\\"/"/g;
				}
			}

			$num_cols = scalar(@cols) if (scalar(@cols) > $num_cols);

			if ($lines > 1) {
				$table .= "<TR>";
				for (my $i = 0; $i < @cols; $i++) {
					$table .= "<TD>" . htmlspecialchars($cols[$i]);
				}
			}
			else {
				@header_cols = @cols;

				unless (scalar(@header_cols) >= 3) {
					$post_mode = 0;
					$upload = 1;
					$feedback = qq!<p><span style="color: red">Invalid data file uploaded.</span> A valid data file should be a CSV file with atleast 3 columns (representing the $pry_key, name and phone number(s)).!;
					unlink "$upload_dir/$file_id";
					last PM;
				}

				$table .= "<THEAD><TR>";
				for (my $i = 0; $i < @cols; $i++) {
					$table .= "<TH>" . htmlspecialchars($cols[$i]);
				}
				$table .= "</THEAD>";
				$table .= "<TBODY>";	
			}
		}

		unless ($lines > 0) {
			$post_mode = 0;
			$upload = 1;
			$feedback = qq!<p><span style="color: red">Blank data file uploaded.</span> The file has been disregarded.!;
			unlink "$upload_dir/$file_id";	
		}

		my $preview = "the complete data";

		#does data have more that 10 rows?
		if ($lines > 10) {
			$preview = "a preview of the data";

			my $rem = $lines - 10;
			$table .= qq!<TR><TD colspan="$num_cols" style="text-align: center; border-style: none">.<TR><TD colspan="$num_cols" style="text-align: center; border-style: none">.<TR><TD colspan="$num_cols" style="text-align: center; border-style: none">.<TR><TD colspan="$num_cols" style="text-align: center; border-style: none"><a href="/cgi-bin/datasets.cgi?act=view_dataset&dataset=$file_id" target="_blank">$rem more rows</a>!;

		}

		$table .= "</TBODY></TABLE>";

		#select column without headers
		
		my $un_headed_id_select = qq!<SELECT name="id_column">!;
		my $un_headed_name_select = qq!<SELECT name="name_column">!;
		my $un_headed_phone_no_select = qq!<SELECT name="phone_no_column" multiple size="4">!;

		for (my $i = 0; $i < $num_cols; $i++) {
			my $user_cnt = $i + 1;
			$un_headed_id_select .= qq!<OPTION id="${pry_key}_Column $user_cnt" onclick=\\'col_selection_changed("${pry_key}", "Column $user_cnt")\\' value="$i">Column $user_cnt</OPTION>!;
			$un_headed_name_select .= qq!<OPTION id="Name_Column $user_cnt" onclick=\\'col_selection_changed("Name", "Column $user_cnt")\\' value="$i">Column $user_cnt</OPTION>!;
			$un_headed_phone_no_select .= qq!<OPTION id="Phone number(s)_Column $user_cnt" onclick=\\'col_selection_changed("Phone number(s)", "Column $user_cnt")\\' value="$i">Column $user_cnt</OPTION>!;
		}

		$un_headed_id_select .= "</SELECT>";
		$un_headed_name_select .= "</SELECT>";
		$un_headed_phone_no_select .= "</SELECT>";

		#select column with headers
		my $headed_id_select = qq!<SELECT name="id_column">!;
		my $headed_name_select = qq!<SELECT name="name_column">!;
		my $headed_phone_no_select = qq!<SELECT name="phone_no_column" multiple size="4">!;

		for (my $j = 0; $j < @header_cols; $j++) {
			my $escaped_header_col = htmlspecialchars($header_cols[$j]);
			$headed_id_select .= qq!<OPTION id="${pry_key}_$escaped_header_col" onclick=\\'col_selection_changed("${pry_key}", "$escaped_header_col")\\' value="$j">! .$escaped_header_col  . "</OPTION>";
			$headed_name_select .= qq!<OPTION id="Name_$escaped_header_col" onclick=\\'col_selection_changed("Name", "$escaped_header_col")\\' value="$j">! . $escaped_header_col . "</OPTION>";
			$headed_phone_no_select .= qq!<OPTION id="Phone number(s)_$escaped_header_col" onclick=\\'col_selection_changed("Phone numbers", "$escaped_header_col")\\' value="$j">! . $escaped_header_col . "</OPTION>";
		}

		$headed_id_select .= "</SELECT>";
		$headed_name_select .= "</SELECT>";
		$headed_phone_no_select .= "</SELECT>";

		
		my $conf_code = gen_token();
		$session{"confirm_code"} = $conf_code;

		my $header =
qq{
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a> --&gt; <a href="/administrator.html">Administrator Panel</a> --&gt; <a href="/messenger/">Messenger</a> --&gt; <a href="/cgi-bin/contacts.cgi">Manage List of Contacts</a> --&gt; <a href="/cgi-bin/contacts.cgi?directory=$directory">$dir_name</a> --&gt; <a href="/cgi-bin/contacts.cgi?directory=$directory&act=upload1">Upload Data</a>
	<hr> 
};

		
		$content = 
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Messenger - Upload Data</title>
<SCRIPT type="text/javascript">

var un_headed_selects = ['$un_headed_id_select','$un_headed_name_select', '$un_headed_phone_no_select'];
var headed_selects = ['$headed_id_select', '$headed_name_select', '$headed_phone_no_select'];

var assigns = [{field: "${pry_key}", columns: []}, {field: "Name", columns: []}, {field: "Phone numbers", columns: []}];
var collisions;

function has_header_changed() {
	var has_header_checked = document.getElementById("has_header_id").checked;
	if (has_header_checked) {
		document.getElementById("id_select").innerHTML = headed_selects[0];
		document.getElementById("name_select").innerHTML = headed_selects[1];
		document.getElementById("phone_no_select").innerHTML = headed_selects[2];
	}
	else {
		document.getElementById("id_select").innerHTML = un_headed_selects[0];
		document.getElementById("name_select").innerHTML = un_headed_selects[1];
		document.getElementById("phone_no_select").innerHTML = un_headed_selects[2];
	}
}

function col_selection_changed(field, column) {

	var already_used = false;

	var is_selected = document.getElementById(field + "_" + column).selected;

	for (var j = 0; j < assigns.length; j++) {
		if (assigns[j].field == field) {
			if (is_selected) {
				assigns[j].columns.push(column);
			}
			else {
				for (var l = 0; l < (assigns[j].columns).length; l++) {
					if ( (assigns[j].columns)[l] == column ) {
						(assigns[j].columns).splice(l,1);
					}
				}
			}
			continue;
		}

		for ( var k = 0; k < (assigns[j].columns).length; k++ ) {
			if ((assigns[j].columns)[k] == column) {
				document.getElementById(field + "_err_asterisk").innerHTML = "\*";
				document.getElementById(field + "_err_msg").innerHTML = "&nbsp;'" + column + "' has also been selected for '" + assigns[j].field + "'";
				already_used = true;
			}
		}
		if (already_used) {
			break;
		}
	}
	if (!already_used) {
		document.getElementById(field + "_err_asterisk").innerHTML = "";
		document.getElementById(field + "_err_msg").innerHTML = "";
	}
}

</SCRIPT>
</head>
<body>
$header
$feedback
<p><em>You are almost done. Just 1 more step...</em>
<p>Below is $preview you uploaded.
$table

<p>
<FORM method="POST" action="/cgi-bin/contacts.cgi?act=upload3&directory=$directory">

<INPUT type="hidden" name="file_id" value="$file_id">

<TABLE>

<TR><TD colspan="2">This data has a header row&nbsp;<INPUT type="checkbox" name="has_header" value="1" id="has_header_id" onclick="has_header_changed()">

<TR><TD colspan="2">Which columns correspond to the following fields:

<TR><TD><span id="id_err_asterisk" style="color: red"></span>$pry_key:<TD><span id="id_select">$un_headed_id_select</span><span id="id_err_msg" style="color: red"></span>

<TR><TD><span id="name_err_asterisk" style="color: red"></span>Name:<TD><span id="name_select">$un_headed_name_select</span><span id="name_err_msg" style="color: red"></span>

<TR><TD><span id="phone_no_err_asterisk" style="color: red"></span>Phone Number(s):<TD><span id="phone_no_select">$un_headed_phone_no_select</span><span id="phone_no_err_msg" style="color: red"></span>

<TR><TD colspan="2"><INPUT type="submit" name="save" value="Save">
</TABLE>

</TABLE>
</FORM>

</body>
</html>
*;

	}
	
	elsif ($upload == 1 and defined $directory and exists $directories{$directory}) {
		my $dir_name = htmlspecialchars(${$directories{$directory}}{"name"});
		my $header =
qq{
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a> --&gt; <a href="/administrator.html">Administrator Panel</a> --&gt; <a href="/messenger/">Messenger</a> --&gt; <a href="/cgi-bin/contacts.cgi">Manage List of Contacts</a> --&gt; <a href="/cgi-bin/contacts.cgi?directory=$directory">$dir_name</a> --&gt; <a href="/cgi-bin/contacts.cgi?directory=$directory&act=upload1">Upload Data</a>
	<hr> 
};

		my $conf_code = gen_token();
		$session{"confirm_code"} = $conf_code;

		$content =
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Messenger - Manage List of Contacts</title>
</head>
<body>
$header
$feedback
<p>Messenger accepts data in the form of CSV (Comma-Separated Values) files. Ensure the data has a <span style="font-weight: bold">header</span>, that the <span style="font-weight: bold">field delimeter</span> is a comma(,) and the <span style="font-weight: bold">text delimiter</span> (if one is necessary) is double quotation marks/inverted commas("").
<p>Most common spreadsheet programs allow you to conveniently save your data as CSV files.  Click on <span style="font-weight: bold">'Save As'</span> (if this is available in your spreadsheet program) and see if Text/CSV is one of the supported formats. Alternatively, check if an <span style="font-weight: bold">'Export'</span> to CSV function is provided. If you've been successful so far, verify that the correct delimeter is used (,) and that 'fixed-width columns' is NOT selected.
<p>If your CSV file is ready, you're ready to go. 
<p>

<FORM method="POST" action="/cgi-bin/contacts.cgi?act=upload2&directory=$directory" enctype="multipart/form-data">
<INPUT type="hidden" name="confirm_code" value="$conf_code">
<TABLE>
<TR>
<TD><LABEL for="csv_file">CSV file</LABEL>
<TD><INPUT type="file" name="csv_file">
<TR>
<TD colspan="2"><INPUT type="submit" name="upload" value="Upload File">
</TABLE>
</FORM>

</body>
</html>
*;
		
	}

	#user wants to edit a specific directory.
	elsif (defined $directory) {
		if ( exists $directories{$directory} ) {
	
			my $conf_code = gen_token();
			$session{"confirm_code"} = $conf_code;

			my $pry_key = ${$directories{$directory}}{"pry_key"};

			my $dir_name = htmlspecialchars(${$directories{$directory}}{"name"});
			my $header =
qq{
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a> --&gt; <a href="/administrator.html">Administrator Panel</a> --&gt; <a href="/messenger/">Messenger</a> --&gt; <a href="/cgi-bin/contacts.cgi">Manage List of Contacts</a> --&gt; <a href="/cgi-bin/contacts.cgi?directory=$directory">$dir_name</a>
	<hr> 
};
			#read this directory
			#will add a LIMIT clause once I get 
			#a little organized -- DONE
			#now to add a search feature
			my @search_vals = ();

			my $search_clause = "";
			my $search_url_bt = "";

			my $search_val = "";

			if ($search and length($search_str) > 0) {

				$search_url_bt = qq!&q=$enc_search_str!;
				$search_val = htmlspecialchars($search_str);

				$search_clause .= " AND ";
				my @search_clause_bts = ();
				my @search_str_bts = split /,/, $search_str;

				for my $search_str_bt (@search_str_bts) {

					#user is searching for a number
					if ( $search_str_bt =~ /^\+?\d+$/ ) {
						push @search_clause_bts, "phone_no LIKE ?";
						
					}
					else {
						push @search_clause_bts, "name LIKE ?";	
					}
					push @search_vals, "%$search_str_bt%";
				}

				if ( scalar(@search_clause_bts) > 1) {
					$search_clause .= "(" . join(" OR ", @search_clause_bts) . ")"; 
				}
				else {
					$search_clause .= "$search_clause_bts[0]";
				}
			}

			my $num_rows = 0;

			my $prep_stmt10 = $con->prepare("SELECT count(id) FROM contacts WHERE directory=?$search_clause");

			if ($prep_stmt10) {
				
				my $rc;
				if ($search) {
					$rc = $prep_stmt10->execute($directory, @search_vals);	
				}
				else {
					$rc = $prep_stmt10->execute($directory);
				}

				if ($rc) {
					$num_rows = ($prep_stmt10->fetchrow_array())[0];	
				}
				else {
					print STDERR "Could not execute SELECT count(id) FROM contacts: ", $con->errstr, $/;
				}
			}
			else {
				print STDERR "Could not prepare SELECT count(id) FROM contacts: ", $con->errstr,$/;
			}

			
			my $row_cnt = 0;

			my $res_per_page = "";
			my $data = ""; 
			my $page_guide = "";

			if ( $num_rows > 0 ) {

				#res per page
				if ($num_rows > 10) {
					$res_per_page .= "<p><em>Results per page</em>: <span style='word-spacing: 1em'>";
					for my $row_cntr (10, 20, 50, 100) {
						if ($row_cntr == $per_page) {
							$res_per_page .= " <span style='font-weight: bold'>$row_cntr</span>";
						}
						else {
							my $re_ordered_page = $page;
							if ($page > 1) {
								my $preceding_results = $per_page * ($page - 1);
								$re_ordered_page = $preceding_results / $row_cntr;
								#if results will overflow into the next
								#page, bump up the page number
								#save that as an integer
								$re_ordered_page++ unless ($re_ordered_page < int($re_ordered_page));
								$re_ordered_page = int($re_ordered_page);
							}
							$res_per_page .= " <a href='/cgi-bin/contacts.cgi?directory=$directory&pg=$re_ordered_page&per_page=$row_cntr${search_url_bt}'>$row_cntr</a>";
						}
					}
					$res_per_page .= "</span><hr>";
				}

				my $res_pages = $num_rows / $per_page;
				if ($res_pages > 1) {
					if (int($res_pages) < $res_pages) {
						$res_pages = int($res_pages) + 1;
					}
				}

				if ($res_pages > 1) {
					$page_guide .= '<p><table cellspacing="50%"><tr>';

					if ($page > 1) {
						$page_guide .= "<td><a href='/cgi-bin/contacts.cgi?directory=$directory&pg=".($page - 1) ."${search_url_bt}'>Prev</a>";
					}

					if ($page < 10) {
						for (my $i = 1; $i <= $res_pages and $i < 11; $i++) {
							if ($i == $page) {
								$page_guide .= "<td><span style='font-weight: bold'>$i</span>";
							}
							else {
								$page_guide .= "<td><a href='/cgi-bin/contacts.cgi?directory=$directory&pg=$i${search_url_bt}'>$i</a>";
							}
						}
					}
					else {
						for (my $i = $page - 4; $i <= $res_pages and $i < ($page + 4); $i++) {
							if ($i == $page) {
								$page_guide .= "<td><span style='font-weight: bold'>$i</span>";
							}
							else {
								$page_guide .= "<td><a href='/cgi-bin/contacts.cgi?directory=$directory&pg=$i${search_url_bt}'>$i</a>";
							}
						}
					}
					if ($page < $res_pages) {
						$page_guide .= "<td><a href='/cgi-bin/contacts.cgi?directory=$directory&pg=".($page + 1)."${search_url_bt}'>Next</a>";
					}
					$page_guide .= '</table>';
				}

				

$data =
qq!
<FORM method="POST" action="/cgi-bin/contacts.cgi?directory=$directory&act=edit">
<INPUT type="hidden" name="confirm_code" value="$conf_code">
<TABLE border="1">
<THEAD>
<TH ><INPUT type="checkbox" id="check_all_box" onclick="check_all()">
<TH>$pry_key
<TH>Name
<TH>Phone Number(s)
</THEAD>
<TBODY>
!;
			my $start = $per_page * ($page - 1);
			my $stop = $start + $per_page;

			my $prep_stmt0 = $con->prepare("SELECT id,name,phone_no FROM contacts WHERE directory=?${search_clause} ORDER BY id ASC LIMIT $start,$stop");
			if ($prep_stmt0) {
				my $rc;

				if ($search) {
					$rc = $prep_stmt0->execute($directory, @search_vals);
				}
				else {
					$rc = $prep_stmt0->execute($directory);
				}
				if ($rc) {
					while ( my @rslts = $prep_stmt0->fetchrow_array() ) {
					
						for (my $k = 0; $k < @rslts; $k++) {
							$rslts[$k] = htmlspecialchars($rslts[$k]);
						}

						my $id = $rslts[0];
						my $phone_no = 
qq!
<span id="${id}-phone_no-1_err" style="color: red"></span><INPUT type="text" value="" id="${id}-phone_no-1" name="edit${row_cnt}-phone_no-1" size="13" onkeyup='edited_old_entry("${id}","phone_no")'><BR>
<span id="${id}-phone_no-2_err" style="color: red"></span><INPUT type="text" value="" id="${id}-phone_no-2" name="edit${row_cnt}-phone_no-2" size="13" onkeyup='edited_old_entry("${id}","phone_no")'><BR>
<span id="${id}-phone_no-3_err" style="color: red"></span><INPUT type="text" value="" id="${id}-phone_no-3" name="edit${row_cnt}-phone_no-3" size="13" onkeyup='edited_old_entry("${id}","phone_no")'><BR>
<span id="${id}-phone_no-4_err" style="color: red"></span><INPUT type="text" value="" id="${id}-phone_no-4" name="edit${row_cnt}-phone_no-4" size="13" onkeyup='edited_old_entry("${id}","phone_no")'>
!;


						if (defined($rslts[2]) and length($rslts[2]) > 0) {

							$phone_no = '';

							my @phone_no_bts = split/,/, $rslts[2];
							my @phone_no_txt_fields = ();

							my $cntr = 1;
							foreach (@phone_no_bts) {
								push @phone_no_txt_fields, qq!<span id="${id}-phone_no-${cntr}_err" style="color: red"></span><INPUT type="text" value="$_" id="${id}-phone_no-$cntr" name="edit${row_cnt}-phone_no-${cntr}" size="13" onkeyup='edited_old_entry("${id}","phone_no")'>!;
								$cntr++;
							}

							#fill surplus with blanks
							for ( ; $cntr < 5; $cntr++ ) {
								push @phone_no_txt_fields, qq!<span id="${id}-phone_no-${cntr}_err" style="color: red"></span><INPUT type="text" value="" id="${id}-phone_no-$cntr" name="edit${row_cnt}-phone_no-${cntr}" size="13" onkeyup='edited_old_entry("${id}","phone_no")'>!;
							}
		
							$phone_no = join("<BR>", @phone_no_txt_fields);
						}

						$data .= 
qq!
<TR>
<TD><INPUT type="checkbox" name="delete${row_cnt}" value="$rslts[0]" id="delete${row_cnt}-check" onclick='check($row_cnt)'>
<TD>$rslts[0]
<INPUT type="hidden" name="edit${row_cnt}-id" value="$rslts[0]">
<TD><span id="${id}-name_err" style="color: red"></span><INPUT type="text" size="32" value="$rslts[1]" id="${id}-name" name="edit${row_cnt}-name" onkeyup='edited_old_entry("${id}","name")'>
<TD>$phone_no
!;
						$row_cnt++;
					}
					$data .= 
qq!
</TBODY>
</TABLE>
<div id="submit_edits">
<p>
<INPUT type="submit" name="save_edits" value="Save Edits">&nbsp;&nbsp;<INPUT type="submit" name="delete" value="Delete Selected">
</div>
<div id="js_edits_save">
</div>
!;
				}
				else {
					print STDERR "Could not execute SELECT id,name FROM contacts_directories: ", $con->errstr, $/;
				}
			}
			else {
				print STDERR "Could not prepare SELECT id,name FROM contacts_directories: ", $con->errstr, $/;
			}
			}

			else {
				$data = "<em>There are no entries in this directory.</em>";
				if ($search) {
					$data = "<em>Your search <em>" . htmlspecialchars($search_str). "</em> did not match any entrues in this directory.</em>";
				} 
			}

			$content =
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Messenger - Manage List of Contacts</title>
<SCRIPT type="text/javascript">

var num_re = new RegExp("^[0-9]+\$");
var phone_num_re = new RegExp('^\\\\+?[0-9]+\$');

var pry_key = "$pry_key";
var num_entries = $row_cnt;

var new_entries = [];
var edited_entries = [];
var deleted_entries = [];

var old_content = '';
 
function clear_default_add_container() {
	document.getElementById("add_container").innerHTML = "";
	document.getElementById("add_button").innerHTML = '<INPUT type="button" id="add" value="Add New Entries" onclick="add_new_entries()">';
	document.getElementById("submit_edits").innerHTML = "";
	document.getElementById("submit_edits").innerHTML = 
'<p>' +
'<INPUT type="button" id="button_save_edits" value="Save Edits" disabled="1" onclick="save_edits()">' +
'&nbsp;&nbsp' +
'<INPUT type="button" id="button_delete" value="Delete Selected" disabled="1" onclick="delete_selected()">';
}

function add_new_entries() {
	document.getElementById("add").disabled = 1;
	document.getElementById("add_dialogue").innerHTML = '<span style="color: red" id="num_entries_err"></span><LABEL for="add_text_field">How many entries do you want to add?</LABEL>&nbsp;&nbsp;<INPUT type="text" id="add_text_field" name="add_text_field" value="" onmousemove="changed_num_entries()" onkeyup="changed_num_entries()"><span id="num_entries_err_msg" style="color: red"></span>';
	
}

function changed_num_entries() {

	var num_new_entries = document.getElementById("add_text_field").value;

	if (num_new_entries.length > 0) {

		if (num_new_entries.match(num_re) && num_new_entries > 0) {
			document.getElementById("num_entries_err").innerHTML = "";
			document.getElementById("num_entries_err_msg").innerHTML = "";
	
			var new_content =
'<TABLE border="1">' + 
'<THEAD>' +
'<TH>&nbsp;' +
'<TH>' + pry_key +
'<TH>Name' +
'<TH>Phone Number(s)' +
'</THEAD>' +
'<TBODY>';

			for ( var i = 0; i < num_new_entries; i++ ) {
				
				var change_event = ' onkeyup="edited_new_entries(' + i + ')" onmousemove="edited_new_entries(' + i + ')"';
				new_content +=
'<TR>' +
'<TD>' + (i+1) + 
'<TD><INPUT type="text" size="10" maxlength="32" id="add' + i + '-id" ' + change_event + '>' +
'<TD><INPUT type="text" size="25" maxlength="32" id="add' + i + '-name"' + change_event+ '>' +
'<TD><span id="add' + i + '-phone_no-1_err" style="color: red"></span><INPUT type="text" size="25" maxlength="32" id="add' + i + '-phone_no-1"' + change_event + '><BR>' +
'<span id="add' + i + '-phone_no-2_err" style="color: red"></span><INPUT type="text" size="25" maxlength="32" id="add' + i + '-phone_no-2"' + change_event + '><BR>' +
'<span id="add' + i + '-phone_no-3_err" style="color: red"></span><INPUT type="text" size="25" maxlength="32" id="add' + i + '-phone_no-3"' + change_event + '><BR>' +
'<span id="add' + i + '-phone_no-4_err" style="color: red"></span><INPUT type="text" size="25" maxlength="32" id="add' + i + '-phone_no-4"' + change_event + '>';

			}
	
			new_content +=
'</TBODY>' +
'</TABLE>' +
'<p><INPUT type="button" id="save_new_entries" name="save" value="Save Changes" disabled="1" onclick="save_new_changes()">';

			document.getElementById("add_container").innerHTML = new_content;
		}

		else {
			document.getElementById("num_entries_err").innerHTML = "\*";
			document.getElementById("num_entries_err_msg").innerHTML = "&nbsp;&nbsp;\*Not a valid number.";
		}
	}
}

function edited_new_entries(cnt) {
	var id = document.getElementById("add" + cnt + "-id").value;

	if (id.length > 0) {
		var name = document.getElementById("add" + cnt + "-name").value;
		var phone_nums_arr = [];
		for (var i = 1; i < 5; i++) {
			var phone_num = document.getElementById("add" + cnt + "-phone_no-" + i).value;
			if (phone_num.length > 0) {
				if (phone_num.match(phone_num_re)) {
					phone_nums_arr.push(phone_num);
					document.getElementById("add" + cnt + "-phone_no-" + i + "_err").innerHTML = "";
				}
				else {
					document.getElementById("add" + cnt + "-phone_no-" + i + "_err").innerHTML = "\*";
				}
			}
		}
		var phone_nums_str = phone_nums_arr.join(",");

		for (var j = 0; j < new_entries.length; j++) {
			if (new_entries[j].cnt == cnt) {
				new_entries.splice(j, 1);
				break;
			}	
		}

		new_entries.push({"cnt": cnt, "id" : id, "name" : name, "phone_nums": phone_nums_str});
			
	}
	else {
		for (var j = 0; j < new_entries.length; j++) {
			if (new_entries[j].cnt == cnt) {
				new_entries.splice(j, 1);
				break;
			}
		}
	}

	if (new_entries.length > 0) {
		document.getElementById("save_new_entries").disabled = 0;
	}
	else {
		document.getElementById("save_new_entries").disabled = 1;
	}
}

function save_new_changes() {
	var seen_ids = [];
	
	for ( var i = new_entries.length - 1; i > -1; i-- ) {

		var dup = false;

		for (var j = 0; j < seen_ids.length; j++) {
			if (new_entries[i].id == seen_ids[j]) {
				dup = true;
				break;
			}
		}

		if (dup) {
			new_entries.splice(i, 1);
		}
		else {
			seen_ids.push(new_entries[i].id);
		}
	}

	if (new_entries.length > 0) {
		old_content = document.getElementById("pre_conf").innerHTML;

		var new_content = 

'<p>' +
"Clicking 'confirm' will save the following new entries:" +
'<FORM method="POST" action="/cgi-bin/contacts.cgi?directory=$directory&act=add">' +
'<INPUT type="hidden" name="confirm_code" value="$conf_code">' +
'<TABLE border="1">' +
'<THEAD>' +
'<TH>' + pry_key +
'<TH>Name' +
'<TH>Phone Number(s)' +
'<TBODY>';

		for (var j = 0; j < new_entries.length; j++) {
			new_content += '<TR><TD>' + htmlspecialchars(new_entries[j].id) + '<TD>' + htmlspecialchars(new_entries[j].name) + '<TD>' + new_entries[j].phone_nums;

			new_content += '<INPUT type="hidden" name="add' + j + '-id" value="' + htmlspecialchars(new_entries[j].id) + '">';
			new_content += '<INPUT type="hidden" name="add' + j + '-name" value="' + htmlspecialchars(new_entries[j].name) + '">';
			new_content += '<INPUT type="hidden" name="add' + j + '-phone_no" value="' + new_entries[j].phone_nums + '">';
		}
new_content += 

'</TBODY>' +
'</TABLE>' +
'<p>' +
'<INPUT type="submit" name="save" value="Save">&nbsp;&nbsp;<INPUT type="button" name="cancel" value="Cancel" onclick="cancel_changes()">' +
'</FORM>';
		document.getElementById("pre_conf").innerHTML = new_content;
		new_entries = [];
	}
}

function cancel_changes() {
	document.getElementById("pre_conf").innerHTML = old_content;
}

function edited_old_entry(id, field) {
	document.getElementById("button_save_edits").disabled = 0;
	
	var seen = false;
	for (var i = 0; i < edited_entries.length; i++) {
		if (edited_entries[i].id == id) {
			seen = true;
			break;
		}
	}

	if (!seen) {
		edited_entries.push({"id" : id, "changed_name" : false, "changed_phone": false});	
	}

	var index = edited_entries.length - 1;

	if ( field == "phone_no" ) {	
		var phone_num_bts = [];
		for (var j = 1; j < 5; j++) {
			var phone_num_n = document.getElementById(id + "-phone_no-" + j).value;
			if (phone_num_n.length > 0) {
				if ( phone_num_n.match(phone_num_re) ) {
					phone_num_bts.push(phone_num_n);
					document.getElementById(id + "-phone_no-" + j + "_err").innerHTML = "";
				}
				else {	
					document.getElementById(id + "-phone_no-" + j + "_err").innerHTML = "\*";
				}
			}
		}

		if (phone_num_bts.length > 0) {
			var phone_num_str = phone_num_bts.join(",");
			edited_entries[index].changed_phone = true;
			edited_entries[index].phone_no = phone_num_str;
		}
		else {
			edited_entries[index].changed_phone = false;
			edited_entries[index].phone_no = "";
		}
	}

	else if (field == "name") {
		var new_name = document.getElementById(id + "-name").value;
		if (new_name.length > 0) {
			edited_entries[index].changed_name = true;
			edited_entries[index].name = new_name;
			document.getElementById(id + "-name_err").innerHTML = "";
		}
		else {
			edited_entries[index].changed_name = false;
			edited_entries[index].name = "";
			document.getElementById(id + "-name_err").innerHTML = "\*";
		}
	}
}

function save_edits() {	
	if (edited_entries.length > 0) {
		old_content = document.getElementById("pre_conf").innerHTML;
		var new_content =
'<FORM method="POST" action="/cgi-bin/contacts.cgi?directory=$directory&act=edit">' +
'<INPUT type="hidden" name="confirm_code" value="$conf_code">' +
'<p>' +
'<em>Clicking confirm will make the following changes:</em>' +
'<TABLE border="1">' +
'<THEAD>' +
'<TH>' + pry_key +
'<TH>Changes' +
'</THEAD>' +
'<TBODY>' +
'';
		for ( var i = 0; i < edited_entries.length; i++ ) {
		
			new_content +=
'<TR>' +
'<TD>' + edited_entries[i].id +
'<TD>';
			new_content += '<INPUT type="hidden" name="edit' + i + '-id" value="' + edited_entries[i].id + '">';

			if (edited_entries[i].changed_name) {
				new_content += "Name: " + htmlspecialchars(edited_entries[i].name);
				new_content += '<INPUT type="hidden" name="edit' + i + '-name" value="' + htmlspecialchars(edited_entries[i].name)  + '">';
			}
			if (edited_entries[i].changed_phone) {
				if (edited_entries[i].changed_name) {
					new_content += "<BR>";
				}
				new_content += "Phone Number(s): " + edited_entries[i].phone_no;
				new_content += '<INPUT type="hidden" name="edit' + i + '-phone_no" value="' + edited_entries[i].phone_no + '">';
			}
		}
		new_content += 
'</TBODY>' +
'</TABLE>' +
'<p>' +
'<INPUT type="submit" name="save_edits" value="Confirm">' +
'&nbsp;&nbsp;' +
'<INPUT type="button" name="cancel" value="Cancel" onclick="cancel_changes()">' +
'</FORM>';
		document.getElementById("pre_conf").innerHTML = new_content;
		edited_entries = [];
	}
}

function check_all() {
	var new_state = document.getElementById("check_all_box").checked;
	
	for (var i = 0; i < num_entries; i++) {
		document.getElementById("delete" + i + "-check").checked = new_state;
	}

	deleted_entries = [];

	if (new_state) {
		for ( var i = 0; i < num_entries; i++ ) {
			var id   = document.getElementById("delete" + i + "-check").value;
			var name = document.getElementById(id + "-name").value;
			deleted_entries.push({"id": id, "name" : name});
		}
		document.getElementById("button_delete").disabled = 0;
	}
	else {
		document.getElementById("button_delete").disabled = 1;
	}	
}

function check(entry) {

	var id = document.getElementById("delete" + entry + "-check").value;
	var checkd = document.getElementById("delete" + entry + "-check").checked;

	if ( checkd ) {
		var name = document.getElementById(id + "-name").value;
		deleted_entries.push({"id" : id, "name" : name});
		document.getElementById("button_delete").disabled = 0;
	}

	else {
		for (var j = 0; j < deleted_entries.length; j++) {
			if ( deleted_entries[j].id == id ) {
				deleted_entries.splice(j, 1);
				break;
			}
		}
		if (deleted_entries.length == 0) {
			document.getElementById("button_delete").disabled = 1;
		}
	}	
}

function delete_selected() {
	if (deleted_entries.length > 0) {
		old_content = document.getElementById("pre_conf").innerHTML;

		var new_content =
'<FORM method="POST" action="/cgi-bin/contacts.cgi?directory=$directory&act=edit">' +
'<INPUT type="hidden" name="confirm_code" value="$conf_code">' +
'<p>' +
"<em>Clicking 'confirm' will delete the following values:</em>" +
'<UL>';
		for ( var i = 0; i < deleted_entries.length; i++ ) {
			new_content += '<INPUT type="hidden" name="delete' + i + '" value="' + htmlspecialchars(deleted_entries[i].id) + '">';
			new_content += '<LI>' + htmlspecialchars(deleted_entries[i].id) + '(' + deleted_entries[i].name + ')';
		}
		new_content +=
'</UL>' +
'<INPUT type="submit" name="delete" value="Confirm">' +
'&nbsp;&nbsp' +
'<INPUT type="button" name="cancel" value="Cancel" onclick="cancel_changes()">' +
'</FORM>';
		document.getElementById("pre_conf").innerHTML = new_content;
		deleted_entries = [];
	}
}

function htmlspecialchars(to_clean) {
        to_clean = to_clean.replace(/</g, "&#60;");
        to_clean = to_clean.replace(/>/g, "&#62;");
        to_clean = to_clean.replace(/'/g, "&#39;");
        to_clean = to_clean.replace(/"/g, "&#34;"); 
        return to_clean;
}

</SCRIPT>
</head>
<body onload="clear_default_add_container()">
$header
<div id="pre_conf">
$feedback
<TABLE width="100%">

<TR>

<TD><a href="/cgi-bin/contacts.cgi?directory=$directory&act=upload1">Upload data to this directory</a>

<TD><a href="/cgi-bin/contacts.cgi?directory=$directory&act=download">Download this directory</a>

<TD>
<FORM method="POST" action="/cgi-bin/contacts.cgi?directory=$directory&act=search">
<INPUT type="hidden" value="$conf_code" name="confirm_code">
<INPUT type="text" value="$search_val" name="search" size="40">
<INPUT type="submit" value="Search Contacts" name="search_button">
</FORM>
</TABLE>
<hr>
<p>

<div id="add_button"></div>

<div id="add_dialogue"></div>

<div id="add_container">

<FORM method="POST" action="/cgi-bin/contacts.cgi?directory=$directory&act=add">
'<INPUT type="hidden" name="confirm_code" value="$conf_code">' +
<TABLE>

<TR>
<TD><LABEL for="add0-id">${$directories{$directory}}{"pry_key"}</LABEL><TD><INPUT type="text" value="" name="add0-id" size="20">

<TR>
<TD><LABEL for="add0-name">Name</LABEL><TD><INPUT type="text" value="" name="add0-id" size="32" maxlength="64">

<TR>
<TD><LABEL for="add0-phone_no-1">Phone Number 1</LABEL><TD><INPUT type="text" value="" name="add0-phone_no-1">
<TR>
<TD><LABEL for="add0-phone_no-2">Phone Number 2</LABEL><TD><INPUT type="text" value="" name="add0-phone_no-2">
<TR>
<TD><LABEL for="add0-phone_no-3">Phone Number 3</LABEL><TD><INPUT type="text" value="" name="add0-phone_no-3">
<TR>
<TD><LABEL for="add0-phone_no-4">Phone Number 4</LABEL><TD><INPUT type="text" value="" name="add0-phone_no-4">

<TR>
<TD colspan="2"><INPUT type="submit" name="add" value="Add Entry">
</TABLE>
</FORM>

<hr>
</div>

<p>
$res_per_page
$data
$page_guide
</div>
</body>
</html>
*;

		}
		else {
			$feedback = qq!<span style="color: red">No such directory.</span> Make your selection from the list below or create a new directory.!;
			$directory = undef;
		}
	}

	#display available directories.
	if ( not defined $directory and not $create_new ) {
		my $conf_code = gen_token();
		$session{"confirm_code"} = $conf_code;

		my $directories_list = qq!<UL style="list-style-type: none">!;;

		foreach ( sort {$a <=> $b} keys %directories ) {	
			$directories_list .= qq!<LI><a href="/cgi-bin/contacts.cgi?directory=$_">${$directories{$_}}{"name"}</a>!;
		}

		$directories_list .= "</UL>";
	
		$content = 
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Messenger - Manage List of Contacts</title>
</head>
<body>
$header
<p>$feedback
<p>Would you like to edit one of the following directories:
$directories_list
<p>Or maybe you want to <a href="/cgi-bin/contacts.cgi?act=new">Create a New Directory</a>?
</body>
</html>
*;
	}
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
$con->disconnect() if (defined $con and $con);

sub gen_token {
	my @key_space = ("A","B","C","D","E","F","0","1","2","3","4","5","6","7","8","9");
	my $len = 5 + int(rand 15);
	if (@_ and ($_[0] eq "1")) {
		@key_space = ("A","B","C","D","E","F","G","H","J","K","L","M","N","P","T","W","X","Z","7","0","1","2","3","4","5","6","7","8","9");
		$len = 10 + int (rand 5);
	}
	my $token = "";
	for (my $i = 0; $i < $len; $i++) {
		$token .= $key_space[int(rand @key_space)];
	}
	return $token;
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

